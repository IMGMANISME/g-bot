from datetime import datetime

import pytest

import app.tools.executor as executor
from app.repositories.notification_repository import NotificationRecord
from app.search_modules.weather import WeatherAnswer
from app.services.restaurant_service import RestaurantResult
from app.tools.executor import ToolContext, execute_tool


@pytest.fixture
def saved(monkeypatch):
    """把建立提醒換成記在清單裡"""
    records = []

    def fake_add(chat_id, message, run_at, repeat_daily):
        record = NotificationRecord(len(records) + 1, chat_id, message, run_at.time(), repeat_daily, run_at)
        records.append(record)
        return record

    monkeypatch.setattr(executor, "add_scheduled_notification", fake_add)
    return records


def ctx(now, text="", prefix=""):
    return ToolContext(chat_id="C1", sender_id="U1", user_text=text, now=now, mention_prefix=prefix)


def reminder(now, saved_list, datetime_text, content="開會", repeat=False, prefix=""):
    return execute_tool("create_reminder", {"datetime": datetime_text, "content": content, "repeat_daily": repeat}, ctx(now, prefix=prefix))


def test_create_one_time_reminder(now, saved):
    result = reminder(now, saved, "2026-10-21 08:00")
    assert result.data == {"status": "created", "when": "明天 08:00", "content": "開會", "repeat_daily": False}
    assert result.fallback_text == "⏰ 好，明天 08:00 提醒你「開會」"
    assert [(q.label, q.text) for q in result.quick_replies] == [("取消這個提醒", "取消提醒 1")]
    assert saved[0].sender_id == "C1"


def test_create_daily_reminder_uses_next_occurrence(now, saved):
    result = reminder(now, saved, "2026-10-20 08:00", content="吃藥", repeat=True)
    assert result.data["when"] == "每天 08:00"
    assert saved[0].next_run_at.date().isoformat() == "2026-10-21"


def test_mention_mode_prefixes_cancel_button(now, saved):
    result = reminder(now, saved, "2026-10-21 08:00", prefix="@G-bot ")
    assert result.quick_replies[0].text == "@G-bot 取消提醒 1"


def test_slightly_past_time_means_right_away(now, saved):
    result = reminder(now, saved, "2026-10-20 14:29", content="關火")
    assert result.data["status"] == "created"
    assert saved[0].next_run_at > now


@pytest.mark.parametrize("datetime_text, content, reason", [
    ("2026-10-20 09:00", "早會", "提醒時間已經過去"),
    ("明天八點", "開會", "看不懂提醒時間"),
    ("2026-10-21 08:00", "", "缺少提醒內容"),
    ("2028-01-01 08:00", "很久以後", "提醒時間超過一年"),
])
def test_invalid_reminder_asks_again(now, saved, datetime_text, content, reason):
    result = reminder(now, saved, datetime_text, content=content)
    assert result.data == {"status": "need_clarification", "reason": reason}
    assert result.quick_replies, "追問時要附範例按鈕"
    assert saved == []


@pytest.fixture
def weather_calls(monkeypatch):
    calls = []

    def fake_lookup(city, dates, focus, today, days=5):
        calls.append({"city": city, "dates": [d.isoformat() for d in dates], "focus": focus})
        return WeatherAnswer("模板", {"ok": True})

    monkeypatch.setattr(executor, "lookup_weather", fake_lookup)
    return calls


def test_weather_prefers_dates_from_original_text(now, weather_calls):
    execute_tool("get_weather", {"city": "台中市", "date": "2026-10-24", "focus": "temperature"}, ctx(now, "週末台中冷不冷"))
    assert weather_calls == [{"city": "臺中市", "dates": ["2026-10-24", "2026-10-25"], "focus": "temperature"}]


def test_weather_uses_model_date_when_text_has_none(now, weather_calls):
    execute_tool("get_weather", {"city": "高雄", "date": "2026-10-21", "focus": "rain"}, ctx(now, "高雄會不會下"))
    assert weather_calls == [{"city": "高雄市", "dates": ["2026-10-21"], "focus": "rain"}]


def test_weather_ignores_unknown_focus(now, weather_calls):
    execute_tool("get_weather", {"city": "臺北市", "focus": "wind"}, ctx(now, "台北風大嗎"))
    assert weather_calls[0]["focus"] == "general"


def test_restaurants_need_location(now, monkeypatch):
    monkeypatch.setattr(executor, "get_restaurant_recommendation",
                        lambda sid, q: RestaurantResult("先傳位置", [], needs_location=True))
    result = execute_tool("recommend_restaurants", {}, ctx(now))
    assert result.data["status"] == "need_location"
    assert result.quick_replies[0].text is None  # 傳送位置按鈕


def test_restaurants_list_is_attached_not_rewritten(now, monkeypatch):
    queries = []

    def fake_recommend(sender_id, query):
        queries.append(query)
        return RestaurantResult("🍽️ 清單", ["p1", "p2"])

    monkeypatch.setattr(executor, "get_restaurant_recommendation", fake_recommend)
    result = execute_tool("recommend_restaurants", {"price": "cheap", "cuisine": "拉麵", "count": 2},
                          ctx(now, "附近有什麼便宜的拉麵"))
    assert result.attachment == "🍽️ 清單"
    assert result.data["restaurant_count"] == 2
    assert (queries[0]["keyword"], queries[0]["max_price"], queries[0]["max_results"]) == ("拉麵", 1, 2)
    assert [q.label for q in result.quick_replies] == ["換一批", "便宜一點", "近一點"]


def test_restaurants_not_found(now, monkeypatch):
    monkeypatch.setattr(executor, "get_restaurant_recommendation", lambda sid, q: RestaurantResult("找不到", []))
    result = execute_tool("recommend_restaurants", {}, ctx(now))
    assert result.data["status"] == "not_found" and result.attachment is None


@pytest.mark.parametrize("hour, minute, spoken", [
    (14, 30, "下午 2 點 30 分"),
    (9, 0, "早上 9 點"),
    (0, 5, "凌晨 12 點 5 分"),
    (12, 30, "中午 12 點 30 分"),
    (20, 45, "晚上 8 點 45 分"),
])
def test_current_time_is_spoken(hour, minute, spoken):
    from tests.conftest import taipei
    result = execute_tool("get_current_time", {}, ctx(taipei(2026, 10, 20, hour, minute)))
    assert result.data == {"time": spoken, "date": "10 月 20 日", "weekday": "星期二"}


def test_unknown_tool(now):
    assert "還不會" in execute_tool("fly_to_moon", {}, ctx(now)).fallback_text


def test_tool_crash_is_contained(now, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("db down")

    monkeypatch.setattr(executor, "add_scheduled_notification", boom)
    result = execute_tool("create_reminder", {"datetime": "2026-10-21 08:00", "content": "開會", "repeat_daily": False}, ctx(now))
    assert result.data == {"error": "工具執行失敗"}
