# app/search_modules/weather.py
import os
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime
from typing import Optional

import requests

from app.utils.logger import setup_logger
from app.utils.time_utils import format_day, now_taipei

logger = setup_logger(__name__)

CWA_API_KEY = os.getenv("CWA_API_KEY")
FORECAST_URL = "https://opendata.cwa.gov.tw/api/v1/rest/datastore/F-D0047-091"
DEFAULT_CITY = "臺中市"

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

RAIN_LIKELY = 50  # 降雨機率達到這個值就提醒帶傘
RAIN_POSSIBLE = 30
HOT_TEMP = 30
COLD_MAX_TEMP = 20  # 最高溫不到這個值，整天都偏冷
COOL_MIN_TEMP = 16  # 最低溫低於這個值，早晚會涼


class WeatherUnavailable(Exception):
    """天氣資料取得失敗，訊息可直接回覆給使用者。"""


@dataclass(frozen=True)
class DayForecast:
    day: date
    weathers: tuple[str, ...]  # 當天各時段的天氣現象，依時間排序、不重複
    min_temp: Optional[int]
    max_temp: Optional[int]
    max_pop: Optional[int]  # 當天各時段中最高的降雨機率（%）

    @property
    def description(self) -> str:
        return "轉".join(self.weathers) or "未知"


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


def _to_int(value) -> Optional[int]:
    return int(value) if str(value).isdigit() else None


def parse_daily_forecast(data: dict) -> list[DayForecast]:
    """把中央氣象署 12 小時一段的預報，整理成每天一筆。"""
    locations = data.get("records", {}).get("Locations", [])
    if not locations or not locations[0].get("Location"):
        return []

    location_data = locations[0]["Location"][0]
    weather_elements = {
        el["ElementName"]: el["Time"]
        for el in location_data.get("WeatherElement", [])
    }

    slots_by_day = defaultdict(list)
    for i, slot in enumerate(weather_elements.get("天氣現象", [])):
        try:
            day = datetime.fromisoformat(slot["StartTime"]).date()
            slots_by_day[day].append({
                "weather": slot["ElementValue"][0].get("Weather", "未知"),
                "min_temp": _to_int(weather_elements["最低溫度"][i]["ElementValue"][0].get("MinTemperature")),
                "max_temp": _to_int(weather_elements["最高溫度"][i]["ElementValue"][0].get("MaxTemperature")),
                "pop": _to_int(weather_elements["12小時降雨機率"][i]["ElementValue"][0].get("ProbabilityOfPrecipitation")),
            })
        except (IndexError, KeyError, ValueError):
            continue

    forecasts = []
    for day in sorted(slots_by_day):
        slots = slots_by_day[day]
        min_temps = [s["min_temp"] for s in slots if s["min_temp"] is not None]
        max_temps = [s["max_temp"] for s in slots if s["max_temp"] is not None]
        pops = [s["pop"] for s in slots if s["pop"] is not None]
        forecasts.append(DayForecast(
            day=day,
            weathers=tuple(dict.fromkeys(s["weather"] for s in slots)),
            min_temp=min(min_temps) if min_temps else None,
            max_temp=max(max_temps) if max_temps else None,
            max_pop=max(pops) if pops else None,
        ))
    return forecasts


def fetch_daily_forecast(city: str) -> list[DayForecast]:
    if not CWA_API_KEY:
        raise WeatherUnavailable("⚠️ 未設置氣象資料的 API 金鑰，請聯絡管理員。")

    try:
        response = requests.get(
            FORECAST_URL,
            params={"Authorization": CWA_API_KEY, "locationName": city},
            timeout=10,
        )
        response.raise_for_status()
        data = response.json()
    except (requests.exceptions.RequestException, ValueError) as e:
        logger.error(f"Weather API error: {e}")
        raise WeatherUnavailable("⚠️ 天氣資料查詢失敗，請稍後再試。")

    forecasts = parse_daily_forecast(data)
    if not forecasts:
        logger.warning(f"天氣資料解析後為空: city={city}")
        raise WeatherUnavailable(f"⚠️ 查無 {city} 的天氣資料。")
    return forecasts


# --- 回覆格式 ---

def _weather_icon(desc: str) -> str:
    if "雷" in desc or "雨" in desc:
        return "🌧️"
    if "陰" in desc:
        return "☁️"
    if "晴" in desc and "雲" in desc:
        return "🌤️"
    if "晴" in desc:
        return "☀️"
    if "雲" in desc:
        return "🌥️"
    return "🌈"


def _temp_text(f: DayForecast) -> str:
    if f.min_temp is None or f.max_temp is None:
        return "氣溫無資料"
    return f"{f.min_temp}–{f.max_temp}°C"


def _pop_text(f: DayForecast) -> str:
    return "降雨機率無資料" if f.max_pop is None else f"降雨機率 {f.max_pop}%"


def _rain_advice(f: DayForecast) -> str:
    if f.max_pop is None:
        return "降雨機率沒有資料，出門前再看一下天空"
    if f.max_pop >= RAIN_LIKELY:
        return f"降雨機率 {f.max_pop}%，記得帶傘 ☔"
    if f.max_pop >= RAIN_POSSIBLE:
        return f"降雨機率 {f.max_pop}%，可能會下雨，帶把傘比較保險"
    return f"降雨機率 {f.max_pop}%，應該不太會下雨"


def _temperature_advice(f: DayForecast) -> str:
    if f.min_temp is None or f.max_temp is None:
        return "氣溫沒有資料"
    if f.max_temp >= HOT_TEMP:
        feel = "會滿熱的，記得多喝水"
    elif f.max_temp <= COLD_MAX_TEMP:
        feel = "偏冷，記得穿外套"
    elif f.min_temp <= COOL_MIN_TEMP:
        feel = "早晚偏涼，記得帶件外套"
    elif f.max_temp - f.min_temp >= 8:
        feel = "早晚溫差大，帶件薄外套"
    else:
        feel = "溫度還算舒服"
    return f"{_temp_text(f)}，{feel}"


def _day_answer(city: str, f: DayForecast, focus: str, today: date) -> str:
    label = format_day(f.day, today)
    icon = _weather_icon(f.description)
    if focus == "rain":
        return f"{label}{city}{_rain_advice(f)}\n（{f.description} {icon}，{_temp_text(f)}）"
    if focus == "temperature":
        return f"{label}{city} {_temperature_advice(f)}\n（{f.description} {icon}，{_pop_text(f)}）"
    tip = "，記得帶傘 ☔" if f.max_pop is not None and f.max_pop >= RAIN_LIKELY else ""
    return f"{label}{city}{f.description} {icon}\n{_temp_text(f)}，{_pop_text(f)}{tip}"


def _multi_day_answer(city: str, forecasts: list[DayForecast], today: date) -> str:
    lines = [f"{city}接下來 {len(forecasts)} 天的天氣："]
    for f in forecasts:
        lines.append(
            f"📅 {format_day(f.day, today)}：{f.description} {_weather_icon(f.description)}，"
            f"{_temp_text(f)}，{_pop_text(f)}"
        )
    rainy = [format_day(f.day, today) for f in forecasts if f.max_pop is not None and f.max_pop >= RAIN_LIKELY]
    if rainy:
        lines.append(f"\n{'、'.join(rainy)}比較可能下雨，記得帶傘 ☔")
    return "\n".join(lines)


@dataclass(frozen=True)
class WeatherAnswer:
    text: str  # 直接可回覆的模板文字
    data: dict  # 給模型改寫用的結構化資料


def _day_data(f: DayForecast, today: date) -> dict:
    label = format_day(f.day, today)
    return {
        "date": label if label.endswith("）") else f"{label} {f.day:%m/%d}",
        "weather": f.description,
        "low_celsius": f.min_temp,
        "high_celsius": f.max_temp,
        "rain_chance_percent": f.max_pop,
    }


def _highlights(forecasts: list[DayForecast], today: date) -> list[str]:
    """多天預報中值得特別提的日子：可能下雨、很熱、偏冷。"""
    notes = []
    for f in forecasts:
        label = format_day(f.day, today)
        if f.max_pop is not None and f.max_pop >= RAIN_LIKELY:
            notes.append(f"{label}降雨機率 {f.max_pop}%，可能會下雨")
        if f.max_temp is not None and f.max_temp >= HOT_TEMP:
            notes.append(f"{label}最高 {f.max_temp} 度，會很熱")
        elif f.max_temp is not None and f.max_temp <= COLD_MAX_TEMP:
            notes.append(f"{label}最高只有 {f.max_temp} 度，偏冷")
    return notes or ["這幾天天氣都蠻穩定的，沒有特別要注意的"]


def lookup_weather(
    city: str | None,
    dates: list[date] | None,
    focus: str,
    today: date,
    days: int = 5,
) -> WeatherAnswer:
    """依問題整理天氣：有指定日期就只取那幾天，focus 決定先講下雨還是溫度。

    focus：rain（會不會下雨）、temperature（冷不冷）、general（一般）
    """
    assumed_city = not city
    city = city or DEFAULT_CITY
    note = f"\n\n（沒說地點，先幫你看{city}）" if assumed_city else ""
    base = {"city": city, "city_was_assumed": assumed_city, "focus": focus}

    def failed(message: str) -> WeatherAnswer:
        return WeatherAnswer(message, {**base, "error": message})

    dates = sorted(set(dates or []))
    if dates and dates[-1] < today:
        return failed("我只查得到今天以後的天氣預報，過去的天氣查不到喔。")

    try:
        forecasts = fetch_daily_forecast(city)
    except WeatherUnavailable as e:
        return failed(str(e))

    forecasts = [f for f in forecasts if f.day >= today] or forecasts
    by_day = {f.day: f for f in forecasts}
    last_day = format_day(forecasts[-1].day, today)

    if not dates:
        # 沒指定日期：問下雨或冷熱時看今天，其他看接下來幾天
        if focus in ("rain", "temperature"):
            found = [forecasts[0]]
            text = _day_answer(city, found[0], focus, today)
            return WeatherAnswer(text + note, {**base, "days": [_day_data(f, today) for f in found]})

        found = forecasts[:days]
        data = {**base, "days": [_day_data(f, today) for f in found], "highlights": _highlights(found, today)}
        return WeatherAnswer(_multi_day_answer(city, found, today) + note, data)

    found = [by_day[d] for d in dates if d in by_day]
    if not found:
        return failed(f"目前預報只到{last_day}，{format_day(dates[0], today)}的天氣還查不到喔。")

    text = "\n\n".join(_day_answer(city, f, focus, today) for f in found)
    data = {**base, "days": [_day_data(f, today) for f in found]}
    if len(found) < len([d for d in dates if d >= today]):
        text += f"\n\n（預報只到{last_day}，之後的還查不到）"
        data["note"] = f"預報只到{last_day}，之後的還查不到"
    return WeatherAnswer(text + note, data)


def answer_weather(
    city: str | None,
    dates: list[date] | None,
    focus: str,
    today: date,
    days: int = 5,
) -> str:
    return lookup_weather(city, dates, focus, today, days).text


def get_weather(city: str = DEFAULT_CITY, days: int = 5) -> str:
    """接下來幾天的天氣預報（不指定日期與重點）。"""
    return answer_weather(city, None, "general", now_taipei().date(), days)
