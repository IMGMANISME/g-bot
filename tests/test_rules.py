import pytest

from app.tools.rules import is_weather_query, match_fast_path


@pytest.mark.parametrize("text, expected_tool", [
    ("台北天氣", "get_weather"),
    ("高雄明天會下雨嗎", "get_weather"),
    ("會下雨嗎", "get_weather"),
    ("週末台中冷不冷", "get_weather"),
    ("明天要不要帶傘", "get_weather"),
    ("昨天天氣如何", "get_weather"),
    ("吃什麼", "recommend_restaurants"),
    ("附近有什麼好吃的", "recommend_restaurants"),
    ("吃什麼 拉麵", "recommend_restaurants"),
    ("現在幾點", "get_current_time"),
    ("今天幾號", "get_current_time"),
    ("提醒我 開會 14:45", "create_reminder"),
    ("提醒我 吃藥 22:00 每天", "create_reminder"),
    ("每五分鐘提醒我測試", "create_reminder"),
    ("提醒我每兩小時喝水", "create_reminder"),
    ("每兩小時提醒我喝水，早上九點到晚上九點", None),  # 有指定時段：交給模型
    ("每十五分鐘提醒我", None),  # 沒有內容：交給模型追問
    # 以下說法不夠明確，交給模型判斷
    ("昨天下雨好煩", None),
    ("下雨天好想睡", None),
    ("我晚餐吃了拉麵", None),
    ("提醒我 吃藥 晚上 8:00", None),
    ("明天早上八點提醒我開會", None),
    ("提醒我 開會 25:00", None),
    ("我今天好累", None),
])
def test_match_fast_path_tool(now, text, expected_tool):
    result = match_fast_path(text, now)
    assert (result[0] if result else None) == expected_tool


def test_weather_args(now):
    assert match_fast_path("高雄明天會下雨嗎", now) == ("get_weather", {"city": "高雄市", "focus": "rain"})
    assert match_fast_path("台中冷不冷", now)[1]["focus"] == "temperature"


def test_strict_reminder_later_today(now):
    _, args = match_fast_path("提醒我 開會 14:45", now)
    assert args == {"datetime": "2026-10-20 14:45", "content": "開會", "repeat_daily": False}


def test_strict_reminder_daily_already_passed_goes_tomorrow(now):
    _, args = match_fast_path("提醒我 吃藥 08:00 每天", now)
    assert args == {"datetime": "2026-10-21 08:00", "content": "吃藥", "repeat_daily": True}


@pytest.mark.parametrize("text, expected", [
    ("高雄會下雨嗎", True),
    ("昨天下雨好煩", False),
    ("溫度幾度", True),
    ("我好熱", False),
])
def test_is_weather_query(now, text, expected):
    assert is_weather_query(text, now) is expected


@pytest.mark.parametrize("text, expected", [
    ("每五分鐘提醒我測試", {"content": "測試", "interval_minutes": 5}),
    ("每兩小時提醒我喝水", {"content": "喝水", "interval_minutes": 120}),
    ("每兩小時提醒我喝水一次", {"content": "喝水", "interval_minutes": 120}),
    ("每半小時叫我起來動一動", {"content": "起來動一動", "interval_minutes": 30}),
    ("每小時提醒我喝水", {"content": "喝水", "interval_minutes": 60}),
    ("每 30 分鐘提醒我看烤箱", {"content": "看烤箱", "interval_minutes": 30}),
    ("每二十分鐘提醒我休息眼睛", {"content": "休息眼睛", "interval_minutes": 20}),
    ("每隔3個小時提醒我吃藥", {"content": "吃藥", "interval_minutes": 180}),
    ("提醒我每兩小時喝水", {"content": "喝水", "interval_minutes": 120}),
    ("提醒我每小時要喝水", {"content": "喝水", "interval_minutes": 60}),
])
def test_recurring_reminder_fast_path(now, text, expected):
    assert match_fast_path(text, now) == ("create_reminder", expected)


@pytest.mark.parametrize("text", ["每天提醒我吃藥", "每半分鐘提醒我看", "每兩小時提醒我喝水，早上九點到晚上九點", "我每兩小時都會喝水"])
def test_unclear_recurring_phrases_go_to_model(now, text):
    assert match_fast_path(text, now) is None


@pytest.mark.parametrize("text, value", [("5", 5), ("五", 5), ("十", 10), ("十五", 15), ("二十", 20), ("三十五", 35), ("一百", None), ("", None)])
def test_parse_number(text, value):
    from app.tools.rules import parse_number
    assert parse_number(text) == value
