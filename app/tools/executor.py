# app/tools/executor.py
"""執行模型要求的工具，並驗證參數。"""
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from app.repositories.notification_repository import add_scheduled_notification
from app.search_modules.weather import find_city, lookup_weather
from app.services.restaurant_service import build_restaurant_query, get_restaurant_recommendation
from app.tools.definitions import CREATE_REMINDER, GET_CURRENT_TIME, GET_WEATHER, RECOMMEND_RESTAURANTS
from app.utils.logger import setup_logger
from app.utils.time_utils import TAIPEI, WEEKDAY_NAMES, find_dates, format_run_at, next_daily_run

logger = setup_logger("tool_executor")

MAX_REMINDER_DAYS_AHEAD = 365
# 模型換算「現在」時可能差個一兩分鐘，這段時間內的過去時間視為「馬上」
PAST_TOLERANCE = timedelta(minutes=2)


@dataclass
class QuickReplyItem:
    label: str
    text: str | None = None  # None 代表「傳送位置」按鈕


@dataclass
class ToolContext:
    chat_id: str  # 提醒、地震等設定存在聊天室底下
    sender_id: str  # 位置、餐廳推薦紀錄跟著個人
    user_text: str
    now: datetime
    mention_prefix: str = ""  # 標記模式下，按鈕文字要加上 @G-bot


@dataclass
class ToolResult:
    data: dict  # 交給模型改寫的結果
    fallback_text: str  # 模型改寫失敗時直接回覆
    attachment: str | None = None  # 附在回覆後面、不經模型改寫的內容（例如餐廳清單與連結）
    quick_replies: list[QuickReplyItem] = field(default_factory=list)


def _parse_date(value) -> datetime | None:
    try:
        return datetime.strptime(str(value), "%Y-%m-%d")
    except ValueError:
        return None


def _run_weather(args: dict, ctx: ToolContext) -> ToolResult:
    city = find_city(args.get("city") or "") or find_city(ctx.user_text)
    # 原句能判斷日期時以原句為準（例如「週末」要兩天，模型通常只給一天）
    dates = find_dates(ctx.user_text, ctx.now.date())
    if not dates and args.get("date"):
        parsed = _parse_date(args["date"])
        dates = [parsed.date()] if parsed else []
    focus = args.get("focus") if args.get("focus") in ("rain", "temperature", "general") else "general"

    answer = lookup_weather(city, dates, focus, ctx.now.date())
    return ToolResult(data=answer.data, fallback_text=answer.text)


def _run_reminder(args: dict, ctx: ToolContext) -> ToolResult:
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


def _run_restaurants(args: dict, ctx: ToolContext) -> ToolResult:
    query = build_restaurant_query(
        ctx.user_text,
        price=args.get("price"),
        cuisine=args.get("cuisine"),
        max_distance_m=args.get("max_distance_m"),
        count=args.get("count"),
    )
    result = get_restaurant_recommendation(ctx.sender_id, query)

    if result.needs_location:
        return ToolResult(
            data={"status": "need_location", "message": "需要使用者先傳送位置才能推薦附近餐廳"},
            fallback_text=result.text,
            quick_replies=[QuickReplyItem("📍 傳送位置")],
        )
    if not result.place_ids:
        return ToolResult(data={"status": "not_found", "message": result.text}, fallback_text=result.text)

    return ToolResult(
        data={
            "status": "found",
            "restaurant_count": len(result.place_ids),
            "note": "餐廳清單（店名、評分、距離、地圖連結）會自動附在你的回覆後面，你只要用一兩句話開場，不要再列出餐廳。",
            "list_preview": result.text[:800],
        },
        fallback_text="幫你找了幾間附近的餐廳：",
        attachment=result.text,
        quick_replies=[
            QuickReplyItem("換一批", f"{ctx.mention_prefix}吃什麼"),
            QuickReplyItem("便宜一點", f"{ctx.mention_prefix}吃什麼 便宜"),
            QuickReplyItem("近一點", f"{ctx.mention_prefix}吃什麼 近一點"),
        ],
    )


def _run_current_time(args: dict, ctx: ToolContext) -> ToolResult:
    now = ctx.now
    period = "凌晨" if now.hour < 6 else "早上" if now.hour < 12 else "中午" if now.hour < 13 else "下午" if now.hour < 18 else "晚上"
    hour12 = now.hour % 12 or 12
    spoken_time = f"{period} {hour12} 點 {now.minute} 分" if now.minute else f"{period} {hour12} 點"
    text = f"現在是{period} {hour12}:{now.minute:02d}，{now.month} 月 {now.day} 日星期{WEEKDAY_NAMES[now.weekday()]}"
    return ToolResult(
        data={"time": spoken_time, "date": f"{now.month} 月 {now.day} 日", "weekday": f"星期{WEEKDAY_NAMES[now.weekday()]}"},
        fallback_text=text,
    )


_HANDLERS = {
    GET_WEATHER: _run_weather,
    CREATE_REMINDER: _run_reminder,
    RECOMMEND_RESTAURANTS: _run_restaurants,
    GET_CURRENT_TIME: _run_current_time,
}


def execute_tool(name: str, args: dict, ctx: ToolContext) -> ToolResult:
    handler = _HANDLERS.get(name)
    if not handler:
        logger.warning(f"模型要求了不存在的工具: {name}")
        return ToolResult(data={"error": f"沒有 {name} 這個工具"}, fallback_text="這個我還不會做耶，換個方式問我看看？")
    try:
        return handler(args or {}, ctx)
    except Exception as e:
        logger.error(f"工具 {name} 執行失敗: {e}", exc_info=True)
        return ToolResult(data={"error": "工具執行失敗"}, fallback_text="⚠️ 我剛剛處理的時候出了點問題，請再試一次。")
