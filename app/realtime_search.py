#app/realtime_search.py
from app.search_modules.weather import answer_weather, find_city
from app.search_modules.time import get_realtime
from app.utils.logger import setup_logger
from app.utils.time_utils import find_dates, now_taipei

logger = setup_logger(__name__)

RAIN_WORDS = ("下雨", "降雨", "下不下雨", "帶傘")
TEMPERATURE_WORDS = ("冷不冷", "熱不熱", "會冷", "會熱", "溫度", "氣溫", "幾度")
QUESTION_WORDS = ("嗎", "？", "?", "會不會", "要不要", "下不下", "冷不冷", "熱不熱", "幾度", "多少")
TIME_TRIGGERS = ("時間", "幾點", "日期", "幾號", "星期幾", "禮拜幾")


def _weather_focus(text: str) -> str:
    if any(word in text for word in RAIN_WORDS):
        return "rain"
    if any(word in text for word in TEMPERATURE_WORDS):
        return "temperature"
    return "general"


def is_weather_query(text: str) -> bool:
    """有「天氣」，或是在問會不會下雨、冷不冷；陳述過去的天氣（昨天下雨好煩）不算。"""
    if "天氣" in text:
        return True
    if _weather_focus(text) == "general":
        return False
    dates = find_dates(text, now_taipei().date())
    if dates and max(dates) < now_taipei().date():
        return False
    return any(word in text for word in QUESTION_WORDS)


# --- 判斷是否需要即時資訊 ---
def needs_realtime_info(text: str) -> bool:
    return is_weather_query(text) or any(word in text for word in TIME_TRIGGERS)

# --- 回傳資訊主邏輯 ---
def get_realtime_info(text: str) -> str:
    if is_weather_query(text):
        today = now_taipei().date()
        return answer_weather(find_city(text), find_dates(text, today), _weather_focus(text), today)

    return get_realtime()
