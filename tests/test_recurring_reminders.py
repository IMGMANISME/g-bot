from datetime import time, timedelta

import pytest

import app.tools.reminders as reminders
from app.repositories.notification_repository import NotificationRecord
from app.tools.base import ToolContext, execute_tool, run_action
from tests.conftest import taipei


@pytest.fixture
def env(monkeypatch):
    """假的資料庫、聊天室人數與推播額度"""
    state = {"saved": [], "quota": {"type": "limited", "limit": 200, "used": 20}}

    def fake_add(chat_id, message, run_at, repeat_daily, interval_minutes=None, window=None, nudge_interval_minutes=None):
        record = NotificationRecord(len(state["saved"]) + 1, chat_id, message, repeat_daily, run_at, interval_minutes,
                                    window.start if window else None, window.end if window else None,
                                    nudge_interval_minutes=nudge_interval_minutes)
        state["saved"].append(record)
        return record

    monkeypatch.setattr(reminders, "add_scheduled_notification", fake_add)
    monkeypatch.setattr(reminders, "get_message_quota", lambda: state["quota"])
    return state


def ctx(now, chat_id="U1", prefix=""):
    return ToolContext(chat_id=chat_id, sender_id="U1", user_text="", now=now, mention_prefix=prefix)


def propose(now, chat_id="U1", **args):
    return execute_tool("create_reminder", {"content": "喝水", **args}, ctx(now, chat_id))


def button(result, label):
    return next(item for item in result.quick_replies if item.label == label)


def test_recurring_reminder_asks_before_creating(env, now):
    result = propose(now, interval_minutes=120)
    assert result.data["status"] == "needs_confirmation"
    assert env["saved"] == []  # 還沒建立
    card = result.attachment
    assert "內容：喝水" in card
    assert "頻率：每 2 小時（09:00–21:00），時段是我先幫你選的" in card
    assert "一天約 7 次，第一次是今天 16:30" in card
    assert "有跟我聊天時，最多每 40 分鐘順便提醒一次（不花推播額度）" in card
    assert "每月大約會用掉 210 則推播，G-Bot 每月推播上限 200 則（本月已用 20 則）" in card
    assert "⚠️ 照這個頻率，本月推播額度可能不夠" in card
    assert [item.label for item in result.quick_replies] == ["確定建立", "改成每 1 小時", "改成每 3 小時", "取消"]
    assert button(result, "確定建立").data.startswith("reminder_confirm:")
    assert button(result, "改成每 1 小時").text == "改成每1小時提醒我喝水"


def test_custom_window_across_midnight(env, now):
    result = propose(now, interval_minutes=60, window_start="22:00", window_end="02:00")
    assert "頻率：每 1 小時（22:00–02:00）\n" in result.attachment + "\n"
    assert "一天約 5 次，第一次是今天 22:00" in result.attachment
    assert button(result, "改成每 2 小時").text == "改成每2小時提醒我喝水，22:00到02:00"


def test_all_day(env, now):
    result = propose(now, interval_minutes=180, window_start="00:00", window_end="00:00")
    assert "每 3 小時（整天）" in result.attachment and "一天約 8 次" in result.attachment


@pytest.mark.parametrize("chat_id", ["C_group", "R_room"])
def test_recurring_reminders_are_not_allowed_in_groups(env, now, chat_id):
    result = propose(now, chat_id=chat_id, interval_minutes=120)
    assert result.data["status"] == "not_allowed_in_group"
    assert "只能在私訊設定" in result.fallback_text
    assert env["saved"] == []


def test_one_time_reminder_is_still_allowed_in_groups(env, now):
    result = execute_tool("create_reminder", {"content": "開會", "datetime": "2026-10-21 08:00"}, ctx(now, "C_group"))
    assert result.data["status"] == "created"


def test_unlimited_quota(env, now):
    env["quota"] = {"type": "none"}
    result = propose(now, interval_minutes=180)
    assert "每月大約會用掉 150 則推播" in result.attachment and "⚠️" not in result.attachment


def test_custom_nudge_interval(env, now):
    data = button(propose(now, interval_minutes=180, nudge_interval_minutes=30), "確定建立").data
    assert "最多每 30 分鐘順便提醒一次" in propose(now, interval_minutes=180, nudge_interval_minutes=30).attachment
    run_action(data, ctx(now))
    assert env["saved"][0].nudge_interval_minutes == 30


def test_confirm_creates_reminder_once(env, now):
    result = propose(now, interval_minutes=120)
    data = button(result, "確定建立").data
    reply = run_action(data, ctx(now))
    assert reply.fallback_text == "⏰ 好，已設定每 2 小時（09:00–21:00）提醒你「喝水」，下一次是今天 16:30。"
    saved = env["saved"][0]
    assert (saved.interval_minutes, saved.window_start, saved.window_end) == (120, time(9), time(21))
    assert reply.quick_replies[0].text == "取消提醒 1"

    assert "過期或建立過了" in run_action(data, ctx(now)).fallback_text  # 連按第二次
    assert len(env["saved"]) == 1


def test_confirm_from_another_chat_is_rejected(env, now):
    data = button(propose(now, interval_minutes=120), "確定建立").data
    assert "過期" in run_action(data, ctx(now, chat_id="U_other")).fallback_text
    assert env["saved"] == []


def test_late_confirmation_moves_first_run(env, now):
    data = button(propose(now, interval_minutes=120), "確定建立").data
    run_action(data, ctx(now + timedelta(hours=3)))  # 17:30 才按
    assert env["saved"][0].next_run_at == taipei(2026, 10, 20, 19, 30)


def test_discard(env, now):
    result = propose(now, interval_minutes=120)
    assert run_action(button(result, "取消").data, ctx(now)).fallback_text == "好，這個提醒就不設定了。"
    assert "過期" in run_action(button(result, "確定建立").data, ctx(now)).fallback_text
    assert env["saved"] == []


def test_missing_time_offers_ways_to_remind(env, now):
    result = execute_tool("create_reminder", {"content": "喝水"}, ctx(now, prefix="@G-bot "))
    assert result.data["status"] == "need_clarification"
    assert [item.text for item in result.quick_replies] == [
        "@G-bot 30分鐘後提醒我喝水", "@G-bot 明天早上8點提醒我喝水", "@G-bot 每2小時提醒我喝水",
    ]


@pytest.mark.parametrize("interval", ["abc", 0, -30])
def test_invalid_interval_asks_again(env, now, interval):
    result = propose(now, interval_minutes=interval)
    assert result.data["status"] == "need_clarification" and env["saved"] == []


def test_unknown_button_action(now):
    assert "失效" in run_action("no_such_action:1", ctx(now)).fallback_text


def test_daily_time_mistakenly_given_as_window_start(env, now):
    """Gemma 實測：「每天晚上十點提醒我吃藥」被填成 window_start/window_end 22:00、沒有 datetime"""
    result = execute_tool(
        "create_reminder",
        {"content": "吃藥", "window_start": "22:00", "window_end": "22:00", "repeat_daily": True},
        ctx(now),
    )
    assert result.data == {"status": "created", "when": "每天 22:00", "content": "吃藥", "repeat_daily": True}
    assert env["saved"][0].repeat_daily and not env["saved"][0].is_recurring
