# app/search_modules/weather.py
import requests
import os
from datetime import datetime
from app.utils.logger import setup_logger

logger = setup_logger(__name__)

CWA_API_KEY = os.getenv("CWA_API_KEY")


def get_weather(city: str = "臺中市", days: int = 5) -> str:
    if not CWA_API_KEY:
        return "⚠️ 未設置氣象資料的 API 金鑰，請聯絡管理員。"

    try:
        url = "https://opendata.cwa.gov.tw/api/v1/rest/datastore/F-D0047-091"
        params = {"Authorization": CWA_API_KEY, "locationName": city}
        response = requests.get(url, params=params, timeout=10)
        response.raise_for_status()
        data = response.json()

        locations = data.get("records", {}).get("Locations", [])
        if not locations or not locations[0].get("Location"):
            return f"⚠️ 查無 {city} 的天氣資料。"

        location_data = locations[0]["Location"][0]
        weather_elements = {
            el["ElementName"]: el["Time"]
            for el in location_data.get("WeatherElement", [])
        }

        time_slots = weather_elements.get("天氣現象", [])
        from collections import defaultdict
        daily_data = defaultdict(list)

        for i in range(len(time_slots)):
            try:
                start = time_slots[i]["StartTime"]
                date_key = datetime.fromisoformat(start).strftime("%Y-%m-%d")

                daily_data[date_key].append({
                    "weather": time_slots[i]["ElementValue"][0].get("Weather", "未知"),
                    "min_temp": weather_elements["最低溫度"][i]["ElementValue"][0].get("MinTemperature", "N/A"),
                    "max_temp": weather_elements["最高溫度"][i]["ElementValue"][0].get("MaxTemperature", "N/A"),
                    "pop": weather_elements["12小時降雨機率"][i]["ElementValue"][0].get("ProbabilityOfPrecipitation", "N/A")
                })
            except (IndexError, KeyError):
                continue

        def get_weekday(date_str: str) -> str:
            week_map = ["一", "二", "三", "四", "五", "六", "日"]
            dt = datetime.strptime(date_str, "%Y-%m-%d")
            return week_map[dt.weekday()]

        def get_weather_icon(desc: str) -> str:
            if "雷" in desc or "雨" in desc:
                return "🌧️"
            elif "陰" in desc and "雨" not in desc:
                return "☁️"
            elif "晴" in desc and "雲" in desc:
                return "🌤️"
            elif "晴" in desc:
                return "☀️"
            elif "雲" in desc:
                return "🌥️"
            else:
                return "🌈"

        output = [f"☀️ {city}未來{days}天天氣預報 ☀️\n"]

        for date in sorted(daily_data.keys())[:days]:
            entries = daily_data[date]
            dt = datetime.strptime(date, "%Y-%m-%d")
            weekday = get_weekday(date)

            weathers = "、".join(set(e["weather"] for e in entries))
            pop_vals = [int(e["pop"]) for e in entries if str(e["pop"]).isdigit()]
            min_temps = [int(e["min_temp"]) for e in entries if str(e["min_temp"]).isdigit()]
            max_temps = [int(e["max_temp"]) for e in entries if str(e["max_temp"]).isdigit()]
            icon = get_weather_icon(weathers)

            pop_text = f"{min(pop_vals)}% ~ {max(pop_vals)}%" if pop_vals else "無資料"
            temp_text = f"{min(min_temps)}°C ~ {max(max_temps)}°C" if min_temps and max_temps else "無資料"

            output.append(f"📅 {dt.strftime('%m/%d')} ({weekday})：{weathers} {icon}，降雨機率 {pop_text}，氣溫 {temp_text}。")

        output.append("\n提醒您，天氣變化多端，出門記得攜帶雨具喔 ☔️")
        return "\n".join(output)

    except requests.exceptions.RequestException as e:
        logger.error(f"Weather API error: {e}")
        return "⚠️ 天氣資料查詢失敗"

# 中央氣象署 F-D0047-091 使用的 22 個縣市名稱
CITY_NAMES = (
    "臺北市", "新北市", "桃園市", "臺中市", "臺南市", "高雄市",
    "基隆市", "新竹市", "嘉義市",
    "新竹縣", "苗栗縣", "彰化縣", "南投縣", "雲林縣", "嘉義縣", "屏東縣",
    "宜蘭縣", "花蓮縣", "臺東縣", "澎湖縣", "金門縣", "連江縣",
)

# 省略「縣/市」的簡稱；新竹、嘉義同時有縣與市，簡稱視為市
CITY_ALIASES = {
    **{name[:-1]: name for name in CITY_NAMES if name not in ("新竹縣", "嘉義縣")},
    "馬祖": "連江縣",
}


def find_city(text: str) -> str | None:
    """從句子中找出縣市名稱，有多個時取最先出現的；找不到回傳 None。"""
    normalized = (text or "").replace("台", "臺")
    best = None
    for keyword, city in [(name, name) for name in CITY_NAMES] + list(CITY_ALIASES.items()):
        pos = normalized.find(keyword)
        if pos == -1:
            continue
        # 同位置時優先完整名稱（較長的關鍵字）
        candidate = (pos, -len(keyword), city)
        if best is None or candidate < best:
            best = candidate
    return best[2] if best else None
