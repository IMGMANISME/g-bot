#app/realtime_search.py
import re
from app.search_modules.weather import get_weather
from app.search_modules.time import get_realtime
from app.utils.logger import setup_logger

logger = setup_logger(__name__)

WEATHER_TRIGGERS = ("天氣",)
TIME_TRIGGERS = ("時間", "幾點", "日期", "幾號", "星期幾", "禮拜幾")

# --- 判斷是否需要即時資訊 ---
def needs_realtime_info(text: str) -> bool:
    return any(word in text for word in WEATHER_TRIGGERS + TIME_TRIGGERS)

# --- 回傳資訊主邏輯 ---
def get_realtime_info(text: str) -> str:
    # ✅ 天氣查詢
    if any(word in text for word in WEATHER_TRIGGERS):
        match = re.search(r"(台|臺)?\S{1,3}[縣市]", text)
        if match:
            city = match.group().replace("台", "臺")
            return get_weather(city)
        else:
            return get_weather()

    # ✅ 時間查詢
    return get_realtime()
