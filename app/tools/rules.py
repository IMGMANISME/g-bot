# app/tools/rules.py
"""說法很明確時直接決定要用哪個工具，省下一次模型判斷。

判斷不了的交給模型（plan_reply），所以這裡寧可漏判也不要誤判。
"""
import re
from datetime import datetime, time as dtime

from app.search_modules.weather import find_city
from app.tools.current_time import GET_CURRENT_TIME
from app.tools.reminders import CREATE_REMINDER
from app.tools.restaurants import RECOMMEND_RESTAURANTS
from app.tools.weather import GET_WEATHER
from app.utils.time_utils import find_dates, next_daily_run

RAIN_WORDS = ("下雨", "降雨", "下不下雨", "帶傘")
TEMPERATURE_WORDS = ("冷不冷", "熱不熱", "會冷", "會熱", "溫度", "氣溫", "幾度")
QUESTION_WORDS = ("嗎", "？", "?", "會不會", "要不要", "下不下", "冷不冷", "熱不熱", "幾度", "多少")
TIME_WORDS = ("幾點", "幾號", "星期幾", "禮拜幾")
RESTAURANT_WORDS = ("吃什麼", "餐廳推薦", "推薦餐廳", "附近餐廳", "附近有什麼好吃")

# 「提醒我 開會 14:30 [每天|一次]」：只接受 HH:MM，其他說法交給模型理解
STRICT_REMINDER = re.compile(r"^提醒我\s+(\S.*?)\s+(\d{1,2}):(\d{2})(?:\s*(每天|一次))?$")
# 內容裡帶有時間詞時（提醒我 吃藥 晚上 8:00），HH:MM 的意思不明確，交給模型
AMBIGUOUS_TIME_WORDS = ("早上", "上午", "中午", "下午", "晚上", "傍晚", "凌晨", "今天", "明天", "後天", "週", "星期", "禮拜", "分鐘", "小時")


def weather_focus(text: str) -> str:
    if any(word in text for word in RAIN_WORDS):
        return "rain"
    if any(word in text for word in TEMPERATURE_WORDS):
        return "temperature"
    return "general"


def is_weather_query(text: str, now: datetime) -> bool:
    """有「天氣」，或是在問會不會下雨、冷不冷；陳述過去的天氣（昨天下雨好煩）不算。"""
    if "天氣" in text:
        return True
    if weather_focus(text) == "general":
        return False
    dates = find_dates(text, now.date())
    if dates and max(dates) < now.date():
        return False
    return any(word in text for word in QUESTION_WORDS)


def parse_strict_reminder(text: str, now: datetime) -> dict | None:
    match = STRICT_REMINDER.match(text.strip())
    if not match:
        return None
    content, hour, minute, repeat = match.group(1).strip(), int(match.group(2)), int(match.group(3)), match.group(4)
    if hour > 23 or minute > 59 or any(word in content for word in AMBIGUOUS_TIME_WORDS):
        return None
    run_at = next_daily_run(dtime(hour, minute), now)
    return {"datetime": run_at.strftime("%Y-%m-%d %H:%M"), "content": content, "repeat_daily": repeat == "每天"}


def match_fast_path(text: str, now: datetime) -> tuple[str, dict] | None:
    """回傳 (工具名稱, 參數)；沒有把握時回傳 None。"""
    reminder = parse_strict_reminder(text, now)
    if reminder:
        return CREATE_REMINDER, reminder

    if is_weather_query(text, now):
        return GET_WEATHER, {"city": find_city(text), "focus": weather_focus(text)}

    if any(word in text for word in RESTAURANT_WORDS):
        return RECOMMEND_RESTAURANTS, {}

    if any(word in text for word in TIME_WORDS) and "天氣" not in text:
        return GET_CURRENT_TIME, {}

    return None
