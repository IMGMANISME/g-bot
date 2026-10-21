"""用自然的說法改設定"""
import pytest

import app.tools.settings as settings
from app.tools.base import ToolContext, execute_tool, run_action


@pytest.fixture
def store(monkeypatch):
    state = {"mode": {}, "quake": {}, "reminders": {"U1": [1, 2]}, "cleared": []}

    monkeypatch.setattr(settings, "get_user_state", lambda cid: state["mode"].get(cid, "active"))
    monkeypatch.setattr(settings, "set_user_state", lambda cid, mode: state["mode"].__setitem__(cid, mode))
    monkeypatch.setattr(settings, "get_earthquake_settings",
                        lambda cid: {"enabled": False, "min_magnitude": None, **state["quake"].get(cid, {})})
    monkeypatch.setattr(settings, "set_earthquake_subscription",
                        lambda cid, enabled: state["quake"].setdefault(cid, {}).update(enabled=enabled))
    monkeypatch.setattr(settings, "set_earthquake_min_magnitude",
                        lambda cid, m: state["quake"].setdefault(cid, {}).update(enabled=True, min_magnitude=m))
    monkeypatch.setattr(settings, "get_user_notifications", lambda cid: state["reminders"].get(cid, []))
    monkeypatch.setattr(settings, "delete_all_notifications_for_user", lambda cid: len(state["reminders"].pop(cid, [])))
    monkeypatch.setattr(settings, "clear_history", lambda mid: state["cleared"].append(mid))
    return state


def ctx(now, chat_id="U1", memory_id="M1"):
    return ToolContext(chat_id=chat_id, sender_id="U1", user_text="", now=now, memory_id=memory_id)


@pytest.mark.parametrize("current, mode, expected", [
    ("active", "silent", "silent"),
    ("mention", "silent", "silent_mention"),  # 保留標記模式
    ("silent_mention", "resume", "mention"),
    ("silent", "resume", "active"),
    ("active", "mention_only", "mention"),
    ("mention", "reply_all", "active"),
])
def test_reply_mode_transitions(store, now, current, mode, expected):
    store["mode"]["C1"] = current
    result = execute_tool("update_reply_mode", {"mode": mode}, ctx(now, "C1"))
    assert store["mode"]["C1"] == expected and result.data["status"] == "changed"


def test_restore_button_undoes_change(store, now):
    store["mode"]["C1"] = "mention"
    result = execute_tool("update_reply_mode", {"mode": "silent"}, ctx(now, "C1"))
    restore = result.quick_replies[0]
    assert restore.label == "復原" and restore.data == "settings_restore_mode:mention"
    assert "只在被標記時回" in run_action(restore.data, ctx(now, "C1")).fallback_text
    assert store["mode"]["C1"] == "mention"


def test_group_modes_not_needed_in_private_chat(store, now):
    result = execute_tool("update_reply_mode", {"mode": "mention_only"}, ctx(now, "U1"))
    assert result.data["status"] == "not_needed" and "U1" not in store["mode"]


def test_unchanged_mode(store, now):
    assert execute_tool("update_reply_mode", {"mode": "resume"}, ctx(now)).data["status"] == "unchanged"


def test_unknown_mode_asks(store, now):
    assert execute_tool("update_reply_mode", {}, ctx(now)).data["status"] == "need_clarification"


@pytest.mark.parametrize("text, resume", [
    ("可以說話了", True), ("你可以講話了", True), ("恢復回覆", True), ("解除靜音", True), ("回來吧", True),
    ("大家可以說話了嗎", False), ("我想說話", False),
])
def test_resume_phrases(text, resume):
    assert settings.is_resume_request(text) is resume


def test_earthquake_on_off_and_threshold(store, now):
    assert "已開啟，規模 4 以上" in execute_tool("update_earthquake_alert", {"enabled": True}, ctx(now)).fallback_text
    off = execute_tool("update_earthquake_alert", {"enabled": False}, ctx(now))
    assert store["quake"]["U1"]["enabled"] is False and off.quick_replies[0].text == "地震通知開"
    assert "規模 5 以上" in execute_tool("update_earthquake_alert", {"min_magnitude": 5}, ctx(now)).fallback_text
    assert store["quake"]["U1"] == {"enabled": True, "min_magnitude": 5.0}
    assert execute_tool("update_earthquake_alert", {"min_magnitude": 12}, ctx(now)).data["status"] == "need_clarification"
    assert execute_tool("update_earthquake_alert", {}, ctx(now)).data["status"] == "need_clarification"


def test_show_settings(store, now):
    store["mode"]["U1"] = "silent"
    text = execute_tool("show_settings", {}, ctx(now)).fallback_text
    assert text == "目前設定：\n回覆模式：靜音\n地震通知：關（規模 4.0 以上）\n提醒：2 個"


def test_clear_conversation_needs_confirmation(store, now):
    result = execute_tool("clear_conversation", {}, ctx(now))
    assert store["cleared"] == [] and [b.label for b in result.quick_replies] == ["確定", "算了"]
    assert "已清除" in run_action(result.quick_replies[0].data, ctx(now)).fallback_text
    assert store["cleared"] == ["M1"]


def test_never_mind(store, now):
    result = execute_tool("clear_conversation", {}, ctx(now))
    assert run_action(result.quick_replies[1].data, ctx(now)).fallback_text == "好，那就不動。"
    assert store["cleared"] == []


def test_cancel_all_reminders_needs_confirmation(store, now):
    result = execute_tool("cancel_all_reminders", {}, ctx(now))
    assert "全部 2 個提醒" in result.fallback_text and store["reminders"]["U1"]
    assert "已取消 2 個提醒" in run_action(result.quick_replies[0].data, ctx(now)).fallback_text
    assert "U1" not in store["reminders"]
    assert execute_tool("cancel_all_reminders", {}, ctx(now)).data["status"] == "empty"


def test_settings_tools_use_templates():
    from app.tools.base import should_rewrite
    names = ("update_reply_mode", "update_earthquake_alert", "show_settings", "clear_conversation", "cancel_all_reminders")
    assert not any(should_rewrite(n) for n in names)
