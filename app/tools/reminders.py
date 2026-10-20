# app/tools/reminders.py
"""提醒：一次性、每天固定時間，以及每隔一段時間的週期提醒（例如每 2 小時提醒喝水）。

週期提醒只能在一對一聊天設定，會先建立草稿並請使用者確認（說明一天幾次、大約用掉多少推播額度），
按「確定建立」才會真的建立。推播時附「喝了」「30 分鐘後再提醒」「今天不用了」按鈕；
使用者有傳訊息時，會在回覆中順便提醒（不花推播額度），下一次推播也跟著延後。
"""
import base64
import uuid
from datetime import datetime, time, timedelta

from app.repositories.notification_repository import (
    NotificationRecord,
    add_scheduled_notification,
    get_notification,
    get_recurring_notifications,
    record_reminded,
    reschedule_notification,
)
from app.services.reminder_schedule import (
    Window, default_nudge_interval, describe_interval, describe_recurrence, is_nudge_due, make_window,
    next_interval_run, parse_clock, runs_per_day, skip_today_run,
)
from app.tools.base import QuickReplyItem, ToolContext, ToolResult, action, postback_data, tool
from app.utils.cache import global_cache
from app.utils.line_utils import get_message_quota
from app.utils.logger import setup_logger
from app.utils.time_utils import TAIPEI, format_run_at, next_daily_run

logger = setup_logger("reminder_tools")

CREATE_REMINDER = "create_reminder"
CONFIRM_DRAFT = "reminder_confirm"
DISCARD_DRAFT = "reminder_discard"
MARK_DONE = "reminder_done"
SNOOZE = "reminder_snooze"
SKIP_TODAY = "reminder_skip_today"
SNOOZE_MINUTES = 30
POSTBACK_DATA_LIMIT = 300  # LINE Postback data 的長度上限

MAX_REMINDER_DAYS_AHEAD = 365
# 模型換算「現在」時可能差個一兩分鐘，這段時間內的過去時間視為「馬上」
PAST_TOLERANCE = timedelta(minutes=2)
# 使用者沒說時段時先建議白天，確認時可以改
DEFAULT_WINDOW = Window(time(9, 0), time(21, 0))
DRAFT_TTL_SECONDS = 10 * 60
DAYS_PER_MONTH = 30
INTERVAL_SUGGESTIONS = (60, 120, 180)


@tool(
    name=CREATE_REMINDER,
    description=(
        "建立提醒。只有在使用者明確要求「提醒我」「叫我」「記得通知我」之類的請求時才使用；"
        "單純陳述行程（例如「我明天要開會」）不要使用。"
        "要每隔一段時間重複提醒（例如每 2 小時提醒喝水）時填 interval_minutes，系統會先請使用者確認再建立。"
    ),
    parameters={
        "type": "OBJECT",
        "properties": {
            "content": {"type": "STRING", "description": "提醒內容，例如 開會、吃藥、喝水"},
            "datetime": {"type": "STRING", "description": "提醒時間，格式 YYYY-MM-DD HH:MM（台北時間）。週期提醒留空"},
            "repeat_daily": {"type": "BOOLEAN", "description": "是否每天在同一個時間提醒"},
            "interval_minutes": {
                "type": "INTEGER",
                "description": "週期提醒：每隔幾分鐘提醒一次，例如每 2 小時填 120。只提醒一次或每天固定時間時留空",
            },
            "window_start": {"type": "STRING", "description": "週期提醒每天開始的時間 HH:MM；使用者沒說就留空"},
            "window_end": {
                "type": "STRING",
                "description": "週期提醒每天結束的時間 HH:MM；使用者沒說就留空。使用者說整天都要提醒時，開始和結束都填 00:00",
            },
            "nudge_interval_minutes": {
                "type": "INTEGER",
                "description": "週期提醒：使用者有跟你聊天時，順便提醒的最短間隔（分鐘）。使用者沒說就留空",
            },
        },
        "required": ["content"],
    },
    rewrite=False,  # 時間與內容要準確，直接用模板回覆
)
def create_reminder(args: dict, ctx: ToolContext) -> ToolResult:
    content = str(args.get("content") or "").strip()
    prefix = ctx.mention_prefix

    if not content:
        return _ask(
            "要提醒你什麼事呢？跟我說一下內容和時間，例如「明天早上八點提醒我開會」。",
            "缺少提醒內容",
            [
                QuickReplyItem("範例：明天早上八點", f"{prefix}明天早上八點提醒我開會"),
                QuickReplyItem("範例：30 分鐘後", f"{prefix}30分鐘後提醒我關火"),
                QuickReplyItem("範例：每 2 小時", f"{prefix}每2小時提醒我喝水"),
            ],
        )

    interval = _to_positive_int(args.get("interval_minutes"))
    if args.get("interval_minutes") not in (None, "") and interval is None:
        return _ask(f"要多久提醒你「{content}」一次呢？例如每 2 小時。", "看不懂提醒間隔", _when_buttons(content, prefix))
    if interval:
        if is_group(ctx.chat_id):
            return ToolResult(
                data={"status": "not_allowed_in_group", "reason": "週期提醒只能在一對一聊天設定"},
                fallback_text=(
                    f"每隔一段時間的提醒（像是定時提醒{content}）只能在私訊設定，"
                    "在群組裡太常推播會吵到大家。加我好友後私訊我再設定一次就好囉。"
                ),
            )
        return propose_recurring(content, interval, args, ctx)

    if not args.get("datetime"):
        return _ask(f"要在什麼時候提醒你「{content}」呢？", "缺少提醒時間", _when_buttons(content, prefix))
    try:
        run_at = TAIPEI.localize(datetime.strptime(str(args["datetime"]), "%Y-%m-%d %H:%M"))
    except ValueError:
        return _ask(f"要在什麼時候提醒你「{content}」呢？", "看不懂提醒時間", _when_buttons(content, prefix))

    repeat_daily = bool(args.get("repeat_daily"))
    if repeat_daily:
        run_at = next_daily_run(run_at.time(), ctx.now)
    elif run_at <= ctx.now:
        if ctx.now - run_at > PAST_TOLERANCE:
            return _ask(
                f"{format_run_at(run_at, False, ctx.now)} 已經過了耶，要改成什麼時候提醒你「{content}」？",
                "提醒時間已經過去",
                _when_buttons(content, prefix),
            )
        run_at = ctx.now + timedelta(minutes=1)
    if run_at - ctx.now > timedelta(days=MAX_REMINDER_DAYS_AHEAD):
        return _ask("我只能設定一年內的提醒喔，要改成什麼時候？", "提醒時間超過一年", _when_buttons(content, prefix))

    record = add_scheduled_notification(ctx.chat_id, content, run_at, repeat_daily)
    when = format_run_at(record.next_run_at, repeat_daily, ctx.now)
    return ToolResult(
        data={"status": "created", "when": when, "content": content, "repeat_daily": repeat_daily},
        fallback_text=f"⏰ 好，{when} 提醒你「{content}」",
        quick_replies=[QuickReplyItem("取消這個提醒", f"{prefix}取消提醒 {record.id}")],
    )


def _ask(message: str, reason: str, quick_replies: list[QuickReplyItem]) -> ToolResult:
    logger.info(f"提醒參數不完整: {reason}")
    return ToolResult(data={"status": "need_clarification", "reason": reason}, fallback_text=message, quick_replies=quick_replies)


def _when_buttons(content: str, prefix: str) -> list[QuickReplyItem]:
    """不知道什麼時候提醒時，提供幾種常見說法（帶著提醒內容，按了就能直接設定）"""
    return [
        QuickReplyItem("30 分鐘後", f"{prefix}30分鐘後提醒我{content}"),
        QuickReplyItem("明天早上 8 點", f"{prefix}明天早上8點提醒我{content}"),
        QuickReplyItem("每 2 小時", f"{prefix}每2小時提醒我{content}"),
    ]


def is_group(chat_id: str) -> bool:
    """LINE 的群組 ID 以 C 開頭、多人聊天室以 R 開頭"""
    return chat_id.startswith(("C", "R"))


def _to_positive_int(value) -> int | None:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


# --- 週期提醒：先確認再建立 ---

def _draft_key(draft_id: str) -> str:
    return f"reminder_draft:{draft_id}"


def _usage_notes(per_day: int) -> list[str]:
    """說明這個頻率大約會用掉多少推播額度"""
    notes = []
    monthly = per_day * DAYS_PER_MONTH
    quota = get_message_quota()
    if quota.get("type") == "limited" and quota.get("limit"):
        limit, used = quota["limit"], quota.get("used") or 0
        notes.append(f"每月大約會用掉 {monthly} 則推播，G-Bot 每月推播上限 {limit} 則（本月已用 {used} 則）")
        if monthly > limit - used:
            notes.append("⚠️ 照這個頻率，本月推播額度可能不夠，用完後提醒會送不出去")
    else:
        notes.append(f"每月大約會用掉 {monthly} 則推播")
    return notes


def propose_recurring(content: str, interval: int, args: dict, ctx: ToolContext) -> ToolResult:
    start, end = parse_clock(args.get("window_start")), parse_clock(args.get("window_end"))
    window_assumed = start is None and end is None
    window = make_window(start or DEFAULT_WINDOW.start, end or DEFAULT_WINDOW.end)
    first_run = next_interval_run(ctx.now, interval, window, ctx.now)
    per_day = runs_per_day(interval, window)
    recurrence = describe_recurrence(interval, window)
    notes = _usage_notes(per_day)
    nudge = _to_positive_int(args.get("nudge_interval_minutes")) or default_nudge_interval(interval)

    draft_id = uuid.uuid4().hex[:12]
    global_cache.set(_draft_key(draft_id), {
        "chat_id": ctx.chat_id,
        "content": content,
        "interval_minutes": interval,
        "window_start": window.start.isoformat() if window else None,
        "window_end": window.end.isoformat() if window else None,
        "first_run": first_run.isoformat(),
        "nudge_interval_minutes": nudge,
    }, ttl=DRAFT_TTL_SECONDS)

    first_run_text = format_run_at(first_run, False, ctx.now)
    card = [
        "📋 提醒設定（還沒建立）",
        f"內容：{content}",
        f"頻率：{recurrence}" + ("，時段是我先幫你選的" if window_assumed else ""),
        f"一天約 {per_day} 次，第一次是{first_run_text}",
        f"有跟我聊天時，最多{describe_interval(nudge)}順便提醒一次（不花推播額度）",
        *notes,
    ]

    prefix = ctx.mention_prefix
    window_hint = f"，{window.start:%H:%M}到{window.end:%H:%M}" if window and not window_assumed else ""
    alternatives = [m for m in INTERVAL_SUGGESTIONS if m != interval][:2]
    return ToolResult(
        data={
            "status": "needs_confirmation",
            "content": content,
            "recurrence": recurrence,
            "runs_per_day": per_day,
            "first_run": first_run_text,
            "window_was_assumed": window_assumed,
            "usage_notes": notes,
            "note": "設定內容、額度說明與按鈕都會附在你的回覆後面，你只用一句口語請使用者確認就好，不要重複任何設定或額度內容。",
        },
        fallback_text=f"要幫你設定「{content}」的週期提醒，確認一下內容：",
        attachment="\n".join(card),
        quick_replies=[
            QuickReplyItem("確定建立", data=postback_data(CONFIRM_DRAFT, draft_id)),
            *[
                QuickReplyItem(f"改成每 {m // 60} 小時", f"{prefix}改成每{m // 60}小時提醒我{content}{window_hint}")
                for m in alternatives
            ],
            QuickReplyItem("取消", data=postback_data(DISCARD_DRAFT, draft_id)),
        ],
    )


def _take_draft(draft_id: str, ctx: ToolContext) -> dict | None:
    """取出草稿並刪除（連按兩次也只會建立一次）；不是這個聊天室的草稿視同不存在"""
    key = _draft_key(draft_id)
    draft = global_cache.get(key)
    if not draft or draft.get("chat_id") != ctx.chat_id:
        return None
    return draft if global_cache.delete(key) else None


EXPIRED_DRAFT_TEXT = "這個設定已經過期或建立過了，要的話再跟我說一次要怎麼提醒你。"


@action(CONFIRM_DRAFT)
def confirm_draft(params: list[str], ctx: ToolContext) -> ToolResult:
    draft = _take_draft(params[0] if params else "", ctx)
    if not draft:
        return ToolResult({}, EXPIRED_DRAFT_TEXT)

    interval = draft["interval_minutes"]
    window = make_window(
        time.fromisoformat(draft["window_start"]) if draft["window_start"] else None,
        time.fromisoformat(draft["window_end"]) if draft["window_end"] else None,
    )
    first_run = datetime.fromisoformat(draft["first_run"])
    if first_run <= ctx.now:  # 確認得比較晚，第一次提醒已經過了
        first_run = next_interval_run(ctx.now, interval, window, ctx.now)

    record = add_scheduled_notification(
        ctx.chat_id, draft["content"], first_run, False, interval, window, draft.get("nudge_interval_minutes"),
    )
    return ToolResult(
        {"status": "created"},
        f"⏰ 好，已設定{describe_recurrence(interval, window)}提醒你「{draft['content']}」，"
        f"下一次是{format_run_at(record.next_run_at, False, ctx.now)}。",
        quick_replies=[QuickReplyItem("取消這個提醒", f"{ctx.mention_prefix}取消提醒 {record.id}")],
    )


@action(DISCARD_DRAFT)
def discard_draft(params: list[str], ctx: ToolContext) -> ToolResult:
    _take_draft(params[0] if params else "", ctx)
    return ToolResult({}, "好，這個提醒就不設定了。")


# --- 提醒送出後的按鈕與順便提醒 ---

def done_label(content: str) -> str:
    """「喝水」→「喝了 ✅」、「吃藥」→「吃了 ✅」，其他→「做完了 ✅」"""
    for verb in ("喝", "吃"):
        if content.startswith(verb):
            return f"{verb}了 ✅"
    return "做完了 ✅"


def _encode(text: str) -> str:
    return base64.urlsafe_b64encode(text.encode()).decode().rstrip("=")


def _decode(text: str) -> str | None:
    try:
        return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4)).decode()
    except (ValueError, UnicodeDecodeError):
        return None


def reminder_buttons(record: NotificationRecord) -> list[QuickReplyItem]:
    """推播或順便提醒時附的按鈕"""
    snooze_label = f"{SNOOZE_MINUTES} 分鐘後再提醒"
    if not record.is_recurring:
        # 一次性提醒送出後就會刪除，把內容放進按鈕資料，按下時才能重建
        data = postback_data(SNOOZE, record.id, SNOOZE_MINUTES, _encode(record.message))
        return [QuickReplyItem(snooze_label, data=data)] if len(data) <= POSTBACK_DATA_LIMIT else []
    snooze = QuickReplyItem(snooze_label, data=postback_data(SNOOZE, record.id, SNOOZE_MINUTES))
    return [
        QuickReplyItem(done_label(record.message), data=postback_data(MARK_DONE, record.id)),
        snooze,
        QuickReplyItem("今天不用了", data=postback_data(SKIP_TODAY, record.id)),
    ]


def due_nudges(chat_id: str, now: datetime) -> list[NotificationRecord]:
    """使用者在一對一聊天傳訊息時，該順便提醒的週期提醒"""
    if is_group(chat_id):
        return []
    return [
        r for r in get_recurring_notifications(chat_id)
        if is_nudge_due(r.interval_minutes, r.nudge_interval_minutes, r.window, r.next_run_at, r.last_reminded_at, now)
    ]


def mark_nudged(record: NotificationRecord, now: datetime) -> None:
    """順便提醒過了：下一次推播從現在重新計算"""
    record_reminded(record.id, now, next_interval_run(now, record.interval_minutes, record.window, now))


def _own_reminder(params: list[str], ctx: ToolContext) -> NotificationRecord | None:
    try:
        record = get_notification(int(params[0]))
    except (IndexError, ValueError):
        return None
    return record if record and record.sender_id == ctx.chat_id else None


GONE_REMINDER_TEXT = "這個提醒已經不存在了，輸入「我的提醒」可以看看目前有哪些。"


@action(MARK_DONE)
def mark_done(params: list[str], ctx: ToolContext) -> ToolResult:
    record = _own_reminder(params, ctx)
    if not record or not record.is_recurring:
        return ToolResult({}, GONE_REMINDER_TEXT)
    next_run = next_interval_run(ctx.now, record.interval_minutes, record.window, ctx.now)
    record_reminded(record.id, ctx.now, next_run, done=True)
    return ToolResult({}, f"👍 讚！下次{format_run_at(next_run, False, ctx.now)}再提醒你{record.message}。")


@action(SNOOZE)
def snooze(params: list[str], ctx: ToolContext) -> ToolResult:
    record = _own_reminder(params, ctx)
    minutes = _to_positive_int(params[1] if len(params) > 1 else None) or SNOOZE_MINUTES
    run_at = ctx.now + timedelta(minutes=minutes)
    if record and record.is_recurring:
        reschedule_notification(record.id, run_at)
    else:
        # 一次性提醒送出後就刪除了：用按鈕裡的內容另外建一個；每日提醒則不影響原本的時間
        content = record.message if record else (_decode(params[2]) if len(params) > 2 else None)
        if not content:
            return ToolResult({}, GONE_REMINDER_TEXT)
        add_scheduled_notification(ctx.chat_id, content, run_at, False)
    return ToolResult({}, f"好，{format_run_at(run_at, False, ctx.now)}再提醒你。")


@action(SKIP_TODAY)
def skip_today(params: list[str], ctx: ToolContext) -> ToolResult:
    record = _own_reminder(params, ctx)
    if not record or not record.is_recurring:
        return ToolResult({}, GONE_REMINDER_TEXT)
    next_run = skip_today_run(record.interval_minutes, record.window, ctx.now)
    record_reminded(record.id, ctx.now, next_run)
    return ToolResult({}, f"好，今天先不提醒了，{format_run_at(next_run, False, ctx.now)}再開始。")
