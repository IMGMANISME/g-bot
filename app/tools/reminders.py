# app/tools/reminders.py
"""提醒：一次性、每天固定時間，以及每隔一段時間的週期提醒（例如每 2 小時提醒喝水）。

週期提醒會先建立草稿並請使用者確認（說明一天幾次、大約用掉多少推播額度），按「確定建立」才會真的建立。
"""
import uuid
from datetime import datetime, time, timedelta

from app.repositories.notification_repository import add_scheduled_notification
from app.services.reminder_schedule import (
    Window, describe_recurrence, make_window, next_interval_run, parse_clock, runs_per_day,
)
from app.tools.base import QuickReplyItem, ToolContext, ToolResult, action, postback_data, tool
from app.utils.cache import global_cache
from app.utils.line_utils import get_chat_member_count, get_message_quota
from app.utils.logger import setup_logger
from app.utils.time_utils import TAIPEI, format_run_at, next_daily_run

logger = setup_logger("reminder_tools")

CREATE_REMINDER = "create_reminder"
CONFIRM_DRAFT = "reminder_confirm"
DISCARD_DRAFT = "reminder_discard"

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
        },
        "required": ["content"],
    },
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
        return _propose_recurring(content, interval, args, ctx)

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


def _to_positive_int(value) -> int | None:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


# --- 週期提醒：先確認再建立 ---

def _draft_key(draft_id: str) -> str:
    return f"reminder_draft:{draft_id}"


def _usage_notes(chat_id: str, per_day: int) -> list[str]:
    """說明這個頻率大約會用掉多少推播額度（群組依人數計算）"""
    members = get_chat_member_count(chat_id)
    notes = []
    if members is None:
        members = 1
        notes.append("查不到群組人數；推播額度是依收到的人數計算")
    elif members > 1:
        notes.append(f"這裡有 {members} 人，每次提醒會算 {members} 則推播額度")

    monthly = per_day * DAYS_PER_MONTH * members
    quota = get_message_quota()
    if quota.get("type") == "limited" and quota.get("limit"):
        limit, used = quota["limit"], quota.get("used") or 0
        notes.append(f"每月大約會用掉 {monthly} 則推播，G-Bot 每月推播上限 {limit} 則（本月已用 {used} 則）")
        if monthly > limit - used:
            notes.append("⚠️ 照這個頻率，本月推播額度可能不夠，用完後提醒會送不出去")
    else:
        notes.append(f"每月大約會用掉 {monthly} 則推播")
    return notes


def _propose_recurring(content: str, interval: int, args: dict, ctx: ToolContext) -> ToolResult:
    start, end = parse_clock(args.get("window_start")), parse_clock(args.get("window_end"))
    window_assumed = start is None and end is None
    window = make_window(start or DEFAULT_WINDOW.start, end or DEFAULT_WINDOW.end)
    first_run = next_interval_run(ctx.now, interval, window, ctx.now)
    per_day = runs_per_day(interval, window)
    recurrence = describe_recurrence(interval, window)
    notes = _usage_notes(ctx.chat_id, per_day)

    draft_id = uuid.uuid4().hex[:12]
    global_cache.set(_draft_key(draft_id), {
        "chat_id": ctx.chat_id,
        "content": content,
        "interval_minutes": interval,
        "window_start": window.start.isoformat() if window else None,
        "window_end": window.end.isoformat() if window else None,
        "first_run": first_run.isoformat(),
    }, ttl=DRAFT_TTL_SECONDS)

    first_run_text = format_run_at(first_run, False, ctx.now)
    card = [
        "📋 提醒設定（還沒建立）",
        f"內容：{content}",
        f"頻率：{recurrence}" + ("，時段是我先幫你選的" if window_assumed else ""),
        f"一天約 {per_day} 次，第一次是{first_run_text}",
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
            "note": "設定內容與按鈕會附在你的回覆後面，你只要用一兩句口語請使用者確認；時段是系統先選的話可以提醒他能改。不要重複列出所有設定。",
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

    record = add_scheduled_notification(ctx.chat_id, draft["content"], first_run, False, interval, window)
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
