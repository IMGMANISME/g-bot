#app/realtime_search.py
import re
import logging
from app.search_modules.weather import get_weather
from app.search_modules.time import get_realtime
from app.search_modules.nba import nba_info
from app.search_modules.tavily_search import get_tavily_search_results

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# --- 判斷是否需要即時資訊 ---
def needs_realtime_info(text: str) -> bool:
    triggers = {
        "天氣", "新聞", "時間", "戰績", "比賽",
        "最新", "目前", "現在", "今天", "剛剛", "即時",
        "查一下", "搜尋", "google", "Google"
    }
    return any(word in text.lower() for word in triggers)

# --- 回傳資訊主邏輯 ---
def get_realtime_info(text: str) -> str:
    lowered_text = text.lower()

    # ✅ 天氣查詢
    if "天氣" in lowered_text:
        match = re.search(r"(台|臺)?\S{1,3}[縣市]", text)
        if match:
            city = match.group().replace("台", "臺")
            return get_weather(city)
        else:
            return get_weather()

    # ✅ 新聞查詢改走 Tavily，避免維護重複的搜尋模組
    match = re.search(r"(.+?)\s*的?新聞|(.+?)新聞", text)
    if match:
        keyword = match.group(1) or match.group(2)
        return get_tavily_search_results(f"{keyword.strip()} 新聞")

    # ✅ NBA 查詢
    if any(word in lowered_text for word in ["戰績", "比賽"]):
        return nba_info(text)

    # ✅ 時間查詢
    if "時間" in lowered_text:
        return get_realtime()

    # ✅ 一般網頁搜尋
    return get_tavily_search_results(text)
