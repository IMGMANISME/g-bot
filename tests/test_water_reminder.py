from datetime import time, timedelta

import pytest

import app.tools.reminders as reminders
import app.tools.water as water
from app.repositories.notification_repository import NotificationRecord
from app.tools.base import ToolContext, execute_tool, run_action
from app.tools.rules import match_fast_path


@pytest.fixture
def env(monkeypatch):
    state = {"existing": []}
    monkeypatch.setattr(water, "get_recurring_notifications", lambda chat_id: state["existing"])
    monkeypatch.setattr(reminders, "get_message_quota", lambda: {"type": "limited", "limit": 200, "used": 0})
    return state


def ctx(now, chat_id="U1"):
    return ToolContext(chat_id=chat_id, sender_id="U1", user_text="", now=now)


@pytest.mark.parametrize("text", ["喝水提醒", "提醒我喝水", "設定喝水提醒", "提醒喝水！"])
def test_water_phrases_use_fast_path(now, text):
    assert match_fast_path(text, now) == ("start_water_reminder", {})


def test_interval_phrase_still_creates_directly(now):
    assert match_fast_path("每兩小時提醒我喝水", now)[0] == "create_reminder"


def test_asks_for_window(env, now):
    result = run_action("water_start", ctx(now))
    assert "要在什麼時段提醒你喝水" in result.fallback_text
    assert "每 3 小時提醒一次，有跟我聊天時最多每 1 小時順便提醒" in result.fallback_text
    assert [b.label for b in result.quick_replies] == ["09:00–21:00", "08:00–22:00", "10:00–23:00", "整天"]
    assert result.quick_replies[0].data == "water_window:0900:2100"


def test_tool_and_button_give_same_question(env, now):
    assert execute_tool("start_water_reminder", {}, ctx(now)).fallback_text == run_action("water_start", ctx(now)).fallback_text


@pytest.mark.parametrize("data, recurrence", [
    ("water_window:0900:2100", "每 3 小時（09:00–21:00）"),
    ("water_window:0000:0000", "每 3 小時（整天）"),
])
def test_choosing_window_shows_confirmation_card(env, now, data, recurrence):
    result = run_action(data, ctx(now))
    assert result.data["status"] == "needs_confirmation"
    assert f"頻率：{recurrence}\n" in result.attachment + "\n"
    assert "有跟我聊天時，最多每 1 小時順便提醒一次" in result.attachment
    assert result.quick_replies[0].label == "確定建立"


def test_existing_water_reminder_is_not_duplicated(env, now):
    env["existing"] = [NotificationRecord(3, "U1", "喝水", False, now + timedelta(hours=1), 180, time(9), time(21))]
    for result in (run_action("water_start", ctx(now)), run_action("water_window:0900:2100", ctx(now))):
        assert "你已經有喝水提醒了：每 3 小時（09:00–21:00），下一次是今天 15:30" in result.fallback_text
        assert [b.text for b in result.quick_replies] == ["取消提醒 3", "我的提醒"]


def test_groups_are_told_to_use_private_chat(env, now):
    result = run_action("water_start", ctx(now, chat_id="C_group"))
    assert result.data["status"] == "not_allowed_in_group" and "私訊" in result.fallback_text


def test_typed_window_is_rewritten_for_the_model(env, now):
    run_action("water_start", ctx(now))
    assert water.take_window_answer("U1", "台北天氣") is None  # 不像在回答時段：照常處理
    assert water.take_window_answer("U1", "早上七點到晚上十點") == "每3小時提醒我喝水，時段是早上七點到晚上十點"
    assert water.take_window_answer("U1", "早上七點到晚上十點") is None  # 只用一次


def test_no_rewrite_without_pending_question(env):
    assert water.take_window_answer("U9", "早上七點到晚上十點") is None


def test_choosing_a_button_clears_pending_question(env, now):
    run_action("water_start", ctx(now))
    run_action("water_window:0900:2100", ctx(now))
    assert water.take_window_answer("U1", "早上七點到晚上十點") is None
