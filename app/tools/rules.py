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
# 週期提醒：「每五分鐘提醒我測試」「每半小時叫我起來動」「提醒我每兩小時喝水」
_EVERY = r"每(?:隔)?\s*(?P<number>[0-9零一二兩三四五六七八九十]+|半)?\s*(?:個)?\s*(?P<unit>分鐘|分|小時|鐘頭)"
RECURRING_REMINDERS = (
    re.compile(rf"^{_EVERY}\s*(?:就)?\s*(?:提醒我|叫我)\s*(?P<content>.+)$"),
    re.compile(rf"^(?:提醒我|叫我)\s*{_EVERY}\s*(?:就)?\s*(?:要)?\s*(?P<content>.+)$"),
)
# 句子裡有指定時段（早上九點到晚上九點）時，交給模型解析
WINDOW_WORDS = ("到", "點", "早上", "上午", "中午", "下午", "晚上", "傍晚", "凌晨", "整天", "從", "之間")
CHINESE_DIGITS = {"零": 0, "一": 1, "二": 2, "兩": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}

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


def parse_number(text: str) -> int | None:
    """阿拉伯數字或一到九十九的中文數字：5、五、十五、二十、三十五"""
    if text.isdigit():
        return int(text)
    if not text or any(ch not in CHINESE_DIGITS and ch != "十" for ch in text):
        return None
    if "十" not in text:
        return CHINESE_DIGITS[text] if len(text) == 1 else None
    tens, _, ones = text.partition("十")
    if len(tens) > 1 or len(ones) > 1:
        return None
    return (CHINESE_DIGITS[tens] if tens else 1) * 10 + (CHINESE_DIGITS[ones] if ones else 0)


def parse_recurring_reminder(text: str) -> dict | None:
    """說法明確的週期提醒；有指定時段或看不懂數字時交給模型"""
    text = text.strip()
    if any(word in text for word in WINDOW_WORDS):
        return None
    match = next((m for m in (pattern.match(text) for pattern in RECURRING_REMINDERS) if m), None)
    if not match:
        return None

    number, unit = match.group("number"), match.group("unit")
    hours = unit in ("小時", "鐘頭")
    if number == "半":
        if not hours:
            return None
        minutes = 30
    else:
        value = 1 if number is None else parse_number(number)
        if not value:
            return None
        minutes = value * 60 if hours else value

    content = match.group("content").strip(" ，,。")
    content = re.sub(r"\s*一次$", "", content)  # 「每兩小時提醒我喝水一次」
    return {"content": content, "interval_minutes": minutes} if content else None


def match_fast_path(text: str, now: datetime) -> tuple[str, dict] | None:
    """回傳 (工具名稱, 參數)；沒有把握時回傳 None。"""
    reminder = parse_strict_reminder(text, now) or parse_recurring_reminder(text)
    if reminder:
        return CREATE_REMINDER, reminder

    if is_weather_query(text, now):
        return GET_WEATHER, {"city": find_city(text), "focus": weather_focus(text)}

    if any(word in text for word in RESTAURANT_WORDS):
        return RECOMMEND_RESTAURANTS, {}

    if any(word in text for word in TIME_WORDS) and "天氣" not in text:
        return GET_CURRENT_TIME, {}

    return None
