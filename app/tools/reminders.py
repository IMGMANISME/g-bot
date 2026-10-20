# app/tools/reminders.py
from datetime import datetime, timedelta

from app.repositories.notification_repository import add_scheduled_notification
from app.tools.base import QuickReplyItem, ToolContext, ToolResult, tool
from app.utils.logger import setup_logger
from app.utils.time_utils import TAIPEI, format_run_at, next_daily_run

logger = setup_logger("reminder_tools")

CREATE_REMINDER = "create_reminder"
MAX_REMINDER_DAYS_AHEAD = 365
# 模型換算「現在」時可能差個一兩分鐘，這段時間內的過去時間視為「馬上」
PAST_TOLERANCE = timedelta(minutes=2)


@tool(
    name=CREATE_REMINDER,
    description=(
        "建立提醒。只有在使用者明確要求「提醒我」「叫我」「記得通知我」之類的請求時才使用；"
        "單純陳述行程（例如「我明天要開會」）不要使用。"
    ),
    parameters={
        "type": "OBJECT",
        "properties": {
            "datetime": {"type": "STRING", "description": "提醒時間，格式 YYYY-MM-DD HH:MM（台北時間）"},
            "content": {"type": "STRING", "description": "提醒內容，例如 開會、吃藥"},
            "repeat_daily": {"type": "BOOLEAN", "description": "是否每天重複"},
        },
        "required": ["datetime", "content", "repeat_daily"],
    },
)
def create_reminder(args: dict, ctx: ToolContext) -> ToolResult:
    content = str(args.get("content") or "").strip()
    repeat_daily = bool(args.get("repeat_daily"))

    def ask(message: str, reason: str) -> ToolResult:
        logger.info(f"提醒參數不完整: {reason} args={args}")
        return ToolResult(
            data={"status": "need_clarification", "reason": reason},
            fallback_text=message,
            quick_replies=[
                QuickReplyItem("範例：明天早上八點", f"{ctx.mention_prefix}明天早上八點提醒我開會"),
                QuickReplyItem("範例：30 分鐘後", f"{ctx.mention_prefix}30分鐘後提醒我關火"),
            ],
        )

    if not content:
        return ask("要提醒你什麼事呢？跟我說一下內容和時間，例如「明天早上八點提醒我開會」。", "缺少提醒內容")

    try:
        run_at = TAIPEI.localize(datetime.strptime(str(args.get("datetime")), "%Y-%m-%d %H:%M"))
    except ValueError:
        return ask(f"要在什麼時候提醒你「{content}」呢？", "看不懂提醒時間")

    if repeat_daily:
        run_at = next_daily_run(run_at.time(), ctx.now)
    elif run_at <= ctx.now:
        if ctx.now - run_at > PAST_TOLERANCE:
            return ask(
                f"{format_run_at(run_at, False, ctx.now)} 已經過了耶，要改成什麼時候提醒你「{content}」？",
                "提醒時間已經過去",
            )
        run_at = ctx.now + timedelta(minutes=1)
    if run_at - ctx.now > timedelta(days=MAX_REMINDER_DAYS_AHEAD):
        return ask("我只能設定一年內的提醒喔，要改成什麼時候？", "提醒時間超過一年")

    record = add_scheduled_notification(ctx.chat_id, content, run_at, repeat_daily)
    when = format_run_at(record.next_run_at, repeat_daily, ctx.now)
    return ToolResult(
        data={"status": "created", "when": when, "content": content, "repeat_daily": repeat_daily},
        fallback_text=f"⏰ 好，{when} 提醒你「{content}」",
        quick_replies=[QuickReplyItem("取消這個提醒", f"{ctx.mention_prefix}取消提醒 {record.id}")],
    )
