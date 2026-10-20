# app/tools/water.py
"""喝水提醒：一鍵建立預設的週期提醒（每 3 小時推播，有聊天時每 1 小時順便提醒），時段讓使用者選。

入口：歡迎訊息與選單的「💧 喝水提醒」按鈕、說「喝水提醒」，或模型判斷使用者想設定喝水提醒時呼叫工具。
選時段的按鈕直接產生確認卡片；使用者自己打字指定時段時，交給模型解析後同樣產生確認卡片。
"""
from app.repositories.notification_repository import NotificationRecord, get_recurring_notifications
from app.services.reminder_schedule import describe_interval, describe_recurrence, default_nudge_interval
from app.tools.base import QuickReplyItem, ToolContext, ToolResult, action, postback_data, tool
from app.tools.reminders import is_group, propose_recurring
from app.utils.cache import global_cache
from app.utils.time_utils import format_run_at

START_WATER_REMINDER = "start_water_reminder"
WATER_START = "water_start"
WATER_WINDOW = "water_window"

WATER_CONTENT = "喝水"
WATER_INTERVAL_MINUTES = 180
PENDING_TTL_SECONDS = 10 * 60
WINDOW_CHOICES = (
    ("09:00–21:00", "09:00", "21:00"),
    ("08:00–22:00", "08:00", "22:00"),
    ("10:00–23:00", "10:00", "23:00"),
    ("整天", "00:00", "00:00"),
)
# 剛問過時段後，使用者打字回答時會出現的字
WINDOW_ANSWER_WORDS = ("到", "點", ":", "：", "早上", "上午", "中午", "下午", "晚上", "凌晨", "整天", "全天")


def _pending_key(chat_id: str) -> str:
    return f"water_window_pending:{chat_id}"


def _existing_water_reminder(chat_id: str) -> NotificationRecord | None:
    return next((r for r in get_recurring_notifications(chat_id) if WATER_CONTENT in r.message), None)


def _not_in_group() -> ToolResult:
    return ToolResult(
        data={"status": "not_allowed_in_group"},
        fallback_text="喝水提醒只能在私訊設定，在群組裡太常推播會吵到大家。加我好友後私訊我，點「💧 喝水提醒」就能開始。",
    )


def _already_set(record: NotificationRecord, ctx: ToolContext) -> ToolResult:
    return ToolResult(
        data={"status": "already_exists"},
        fallback_text=(
            f"你已經有喝水提醒了：{describe_recurrence(record.interval_minutes, record.window)}，"
            f"下一次是{format_run_at(record.next_run_at, False, ctx.now)}。"
        ),
        quick_replies=[
            QuickReplyItem("取消喝水提醒", f"{ctx.mention_prefix}取消提醒 {record.id}"),
            QuickReplyItem("我的提醒", f"{ctx.mention_prefix}我的提醒"),
        ],
    )


def ask_window(ctx: ToolContext) -> ToolResult:
    """問使用者要在什麼時段提醒；已經有喝水提醒就不重複建立"""
    if is_group(ctx.chat_id):
        return _not_in_group()
    existing = _existing_water_reminder(ctx.chat_id)
    if existing:
        return _already_set(existing, ctx)

    global_cache.set(_pending_key(ctx.chat_id), True, ttl=PENDING_TTL_SECONDS)
    nudge = describe_interval(default_nudge_interval(WATER_INTERVAL_MINUTES))
    return ToolResult(
        data={"status": "asking_window"},
        fallback_text=(
            f"💧 要在什麼時段提醒你喝水呢？\n"
            f"{describe_interval(WATER_INTERVAL_MINUTES)}提醒一次，有跟我聊天時最多{nudge}順便提醒（不花推播額度）。\n"
            "也可以直接打字告訴我，例如「早上七點到晚上十點」。"
        ),
        quick_replies=[
            QuickReplyItem(label, data=postback_data(WATER_WINDOW, start.replace(":", ""), end.replace(":", "")))
            for label, start, end in WINDOW_CHOICES
        ],
    )


@tool(
    name=START_WATER_REMINDER,
    description=(
        "使用者想設定喝水提醒、但沒有說要多久提醒一次時使用，會請使用者選擇提醒的時段。"
        "使用者有說間隔（例如每兩小時提醒我喝水）時改用 create_reminder。"
    ),
    rewrite=False,
)
def start_water_reminder(args: dict, ctx: ToolContext) -> ToolResult:
    return ask_window(ctx)


@action(WATER_START)
def water_start(params: list[str], ctx: ToolContext) -> ToolResult:
    return ask_window(ctx)


@action(WATER_WINDOW)
def water_window(params: list[str], ctx: ToolContext) -> ToolResult:
    """選了時段：產生確認卡片（按「確定建立」才會真的建立）"""
    global_cache.delete(_pending_key(ctx.chat_id))
    if is_group(ctx.chat_id):
        return _not_in_group()
    existing = _existing_water_reminder(ctx.chat_id)
    if existing:
        return _already_set(existing, ctx)

    try:
        start, end = (f"{p[:2]}:{p[2:]}" for p in params[:2])
    except ValueError:
        return ask_window(ctx)
    return propose_recurring(WATER_CONTENT, WATER_INTERVAL_MINUTES, {"window_start": start, "window_end": end}, ctx)


def take_window_answer(chat_id: str, text: str) -> str | None:
    """剛問過時段、而且這句看起來在回答時段時，改寫成完整的設定句交給模型解析；否則回傳 None"""
    key = _pending_key(chat_id)
    if not global_cache.get(key) or not any(word in text for word in WINDOW_ANSWER_WORDS):
        return None
    global_cache.delete(key)
    return f"每{WATER_INTERVAL_MINUTES // 60}小時提醒我喝水，時段是{text}"
