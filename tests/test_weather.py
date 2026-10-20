from datetime import date

import pytest

import app.search_modules.weather as weather
from app.search_modules.weather import WeatherUnavailable, find_city, lookup_weather, parse_daily_forecast

TODAY = date(2026, 10, 20)


@pytest.mark.parametrize("text, expected", [
    ("台北市天氣", "臺北市"),
    ("今天台北市天氣", "臺北市"),
    ("台北天氣", "臺北市"),
    ("新北天氣", "新北市"),
    ("新竹天氣", "新竹市"),
    ("新竹縣天氣", "新竹縣"),
    ("嘉義天氣", "嘉義市"),
    ("嘉義縣天氣", "嘉義縣"),
    ("台東天氣", "臺東縣"),
    ("馬祖天氣", "連江縣"),
    ("台南跟台北天氣", "臺南市"),
    ("今天天氣如何", None),
])
def test_find_city(text, expected):
    assert find_city(text) == expected


def test_parse_daily_forecast_groups_slots_by_day(week_forecast):
    first = week_forecast[0]
    assert first.day == TODAY
    assert first.description == "多雲時晴轉晴時多雲"
    assert (first.min_temp, first.max_temp, first.max_pop) == (20, 27, 10)
    assert week_forecast[1].max_pop == 70
    # 降雨機率「-」視為沒有資料
    assert week_forecast[6].max_pop is None


def test_parse_daily_forecast_empty_payload():
    assert parse_daily_forecast({}) == []


@pytest.fixture
def forecast(monkeypatch, week_forecast):
    requested = []

    def fake_fetch(city):
        requested.append(city)
        return week_forecast

    monkeypatch.setattr(weather, "fetch_daily_forecast", fake_fetch)
    return requested


def test_rain_question_for_specific_day(forecast):
    answer = lookup_weather("高雄市", [date(2026, 10, 21)], "rain", TODAY)
    assert answer.text.startswith("明天高雄市降雨機率 70%，記得帶傘")
    assert answer.data["days"][0]["rain_chance_percent"] == 70
    assert forecast == ["高雄市"]


def test_temperature_question_for_weekend(forecast):
    answer = lookup_weather("臺中市", [date(2026, 10, 24), date(2026, 10, 25)], "temperature", TODAY)
    assert "10/24（六）臺中市 15–26°C，早晚偏涼" in answer.text
    assert "10/25（日）臺中市 18–25°C，溫度還算舒服" in answer.text
    assert len(answer.data["days"]) == 2


def test_cold_day(forecast):
    answer = lookup_weather("新竹市", [date(2026, 10, 23)], "temperature", TODAY)
    assert "13–19°C，偏冷，記得穿外套" in answer.text


def test_general_lists_days_with_highlights(forecast):
    answer = lookup_weather("臺北市", None, "general", TODAY)
    assert answer.text.startswith("臺北市接下來 5 天的天氣")
    assert "明天比較可能下雨，記得帶傘" in answer.text
    assert answer.data["highlights"] == [
        "明天降雨機率 70%，可能會下雨",
        "後天最高 31 度，會很熱",
        "10/23（五）最高只有 19 度，偏冷",
    ]


def test_missing_city_defaults_and_says_so(forecast):
    answer = lookup_weather(None, None, "rain", TODAY)
    assert forecast == ["臺中市"]
    assert "沒說地點，先幫你看臺中市" in answer.text
    assert answer.data["city_was_assumed"] is True


def test_past_date_is_explained_without_fetching(forecast):
    answer = lookup_weather("臺北市", [date(2026, 10, 19)], "general", TODAY)
    assert "過去的天氣查不到" in answer.text
    assert forecast == []


def test_date_beyond_forecast(forecast):
    answer = lookup_weather("臺北市", [date(2026, 10, 30)], "general", TODAY)
    assert "預報只到10/26（一）" in answer.text and "error" in answer.data


def test_fetch_failure_is_reported(monkeypatch):
    def fail(city):
        raise WeatherUnavailable("⚠️ 天氣資料查詢失敗，請稍後再試。")

    monkeypatch.setattr(weather, "fetch_daily_forecast", fail)
    answer = lookup_weather("臺北市", None, "general", TODAY)
    assert answer.text == "⚠️ 天氣資料查詢失敗，請稍後再試。"
    assert answer.data["error"] == answer.text
