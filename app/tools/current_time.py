# app/tools/current_time.py
from app.tools.base import ToolContext, ToolResult, tool
from app.utils.time_utils import WEEKDAY_NAMES

GET_CURRENT_TIME = "get_current_time"


@tool(
    name=GET_CURRENT_TIME,
    description="取得現在的日期、時間與星期。使用者問現在幾點、今天幾號、星期幾時使用。",
)
def get_current_time(args: dict, ctx: ToolContext) -> ToolResult:
    now = ctx.now
    period = "凌晨" if now.hour < 6 else "早上" if now.hour < 12 else "中午" if now.hour < 13 else "下午" if now.hour < 18 else "晚上"
    hour12 = now.hour % 12 or 12
    spoken_time = f"{period} {hour12} 點 {now.minute} 分" if now.minute else f"{period} {hour12} 點"
    text = f"現在是{period} {hour12}:{now.minute:02d}，{now.month} 月 {now.day} 日星期{WEEKDAY_NAMES[now.weekday()]}"
    return ToolResult(
        data={"time": spoken_time, "date": f"{now.month} 月 {now.day} 日", "weekday": f"星期{WEEKDAY_NAMES[now.weekday()]}"},
        fallback_text=text,
    )
