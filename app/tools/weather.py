# app/tools/weather.py
from datetime import datetime

from app.search_modules.weather import find_city, lookup_weather
from app.tools.base import ToolContext, ToolResult, tool
from app.utils.time_utils import find_dates

GET_WEATHER = "get_weather"


@tool(
    name=GET_WEATHER,
    description="查詢台灣縣市的天氣預報。使用者詢問天氣、會不會下雨、要不要帶傘、冷不冷、溫度時使用。",
    parameters={
        "city": {"type": "STRING", "description": "縣市全名，例如 臺北市、高雄市、花蓮縣。使用者沒提到時留空"},
        "date": {"type": "STRING", "description": "要查詢的日期，格式 YYYY-MM-DD；沒有指定日期時留空"},
        "focus": {
            "type": "STRING",
            "enum": ["rain", "temperature", "general"],
            "description": "使用者最關心的面向：rain 降雨、temperature 冷熱溫度、general 一般",
        },
    },
)
def get_weather(args: dict, ctx: ToolContext) -> ToolResult:
    city = find_city(args.get("city") or "") or find_city(ctx.user_text)
    # 原句能判斷日期時以原句為準（例如「週末」要兩天，模型通常只給一天）
    dates = find_dates(ctx.user_text, ctx.now.date())
    if not dates and args.get("date"):
        try:
            dates = [datetime.strptime(str(args["date"]), "%Y-%m-%d").date()]
        except ValueError:
            dates = []
    focus = args.get("focus") if args.get("focus") in ("rain", "temperature", "general") else "general"

    answer = lookup_weather(city, dates, focus, ctx.now.date())
    return ToolResult(data=answer.data, fallback_text=answer.text)
