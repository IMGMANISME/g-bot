"""用自然的說法查詢、回報完成、取消提醒"""
from datetime import time, timedelta

import pytest

import app.tools.reminders as reminders
from app.repositories.notification_repository import NotificationRecord
from app.tools.base import ToolContext, execute_tool
from app.tools.rules import match_fast_path


@pytest.fixture
def table(monkeypatch, now):
    rows = {
        1: NotificationRecord(1, "U1", "喝水", False, now + timedelta(hours=1), 180, time(9), time(21)),
        2: NotificationRecord(2, "U1", "開會", False, now + timedelta(days=1)),
        3: NotificationRecord(3, "U1", "吃藥", True, now + timedelta(hours=8)),
    }

    def recurring(chat_id):
        return [r for r in rows.values() if r.sender_id == chat_id and r.is_recurring]

    def user_rows(chat_id):
        return sorted((r for r in rows.values() if r.sender_id == chat_id), key=lambda r: r.next_run_at)

    def delete(chat_id, id_):
        return rows.pop(id_, None) is not None if rows.get(id_) and rows[id_].sender_id == chat_id else False

    def record_reminded(id_, at, next_run_at, done=False):
        old = rows[id_]
        rows[id_] = NotificationRecord(**{**old.__dict__, "next_run_at": next_run_at, "last_reminded_at": at})

    monkeypatch.setattr(reminders, "get_recurring_notifications", recurring)
    monkeypatch.setattr(reminders, "get_user_notifications", user_rows)
    monkeypatch.setattr(reminders, "delete_notification_by_id", delete)
    monkeypatch.setattr(reminders, "get_notification", lambda id_: rows.get(id_))
    monkeypatch.setattr(reminders, "record_reminded", record_reminded)
    return rows


def ctx(now, chat_id="U1"):
    return ToolContext(chat_id=chat_id, sender_id="U1", user_text="", now=now)


# --- 快速通道 ---

@pytest.mark.parametrize("text, expected", [
    ("我剛喝了水", ("mark_reminder_done", {"content": "喝水"})),
    ("喝了", ("mark_reminder_done", {"content": "喝水"})),
    ("喝了～", ("mark_reminder_done", {"content": "喝水"})),
    ("不用再提醒我喝水了", ("cancel_reminder", {"content": "喝水"})),
    ("不要提醒我喝水", ("cancel_reminder", {"content": "喝水"})),
    ("取消喝水提醒", ("cancel_reminder", {"content": "喝水"})),
    ("關掉喝水的提醒", ("cancel_reminder", {"content": "喝水"})),
    ("取消明天開會的提醒", ("cancel_reminder", {"content": "明天開會"})),
    ("取消提醒 喝水", ("cancel_reminder", {"content": "喝水"})),
    ("我喝了咖啡", None),
    ("我喜歡喝水", None),
    ("不用了", None),
])
def test_fast_path(now, text, expected):
    assert match_fast_path(text, now) == expected


def test_cancel_by_id_is_still_a_command():
    from app.handlers.command_handler import ReminderCommandHandler
    handler = ReminderCommandHandler()
    assert handler.can_handle("取消提醒 3", {}) and handler.can_handle("取消提醒 3 5", {}) and handler.can_handle("取消提醒", {})
    assert not handler.can_handle("取消提醒 喝水", {})


# --- 查詢 ---

def test_list_reminders(table, now):
    result = execute_tool("list_reminders", {}, ctx(now))
    assert result.fallback_text.splitlines() == [
        "📋你的提醒列表：",
        "• 編號 1｜每 3 小時（09:00–21:00），下一次今天 15:30｜喝水",
        "• 編號 3｜每天 22:30｜吃藥",
        "• 編號 2｜明天 14:30｜開會",
    ]
    assert [b.label for b in result.quick_replies] == ["刪除全部提醒", "取消提醒 1", "取消提醒 3", "取消提醒 2", "取消"]


def test_list_when_empty(table, now):
    result = execute_tool("list_reminders", {}, ctx(now, chat_id="U_empty"))
    assert "沒有任何提醒" in result.fallback_text


# --- 回報完成 ---

def test_mark_done_restarts_interval(table, now):
    result = execute_tool("mark_reminder_done", {"content": "喝水"}, ctx(now))
    assert table[1].next_run_at == now + timedelta(hours=3)
    assert result.fallback_text == "👍 讚！下次今天 17:30再提醒你喝水。"


def test_mark_done_without_water_reminder_offers_setup(table, now):
    del table[1]
    result = execute_tool("mark_reminder_done", {"content": "喝水"}, ctx(now))
    assert "要不要設定一個" in result.fallback_text
    assert result.quick_replies[0].data == "water_start"


def test_mark_done_other_content_without_reminder(table, now):
    result = execute_tool("mark_reminder_done", {"content": "伸展"}, ctx(now))
    assert "沒有關於「伸展」的週期提醒" in result.fallback_text


def test_mark_done_ambiguous_asks_which(table, now):
    table[4] = NotificationRecord(4, "U1", "喝水（公司）", False, now + timedelta(hours=2), 120, time(9), time(18))
    result = execute_tool("mark_reminder_done", {"content": "喝水"}, ctx(now))
    assert result.data["status"] == "ambiguous"
    assert [b.data for b in result.quick_replies] == ["reminder_done:1", "reminder_done:4"]
    assert all(len(b.label) <= 20 for b in result.quick_replies)


# --- 取消 ---

def test_cancel_by_content(table, now):
    result = execute_tool("cancel_reminder", {"content": "喝水"}, ctx(now))
    assert 1 not in table
    assert result.fallback_text == "好，已取消「喝水」的提醒（每 3 小時（09:00–21:00），下一次今天 15:30）。"


def test_cancel_with_longer_phrase_still_matches(table, now):
    execute_tool("cancel_reminder", {"content": "明天開會"}, ctx(now))
    assert 2 not in table


def test_cancel_by_id(table, now):
    execute_tool("cancel_reminder", {"reminder_id": 3}, ctx(now))
    assert 3 not in table and 1 in table


def test_cancel_not_found(table, now):
    result = execute_tool("cancel_reminder", {"content": "遛狗"}, ctx(now))
    assert result.data["status"] == "not_found" and len(table) == 3


def test_cancel_ambiguous_asks_which(table, now):
    table[4] = NotificationRecord(4, "U1", "喝水（公司）", False, now + timedelta(hours=2), 120, time(9), time(18))
    result = execute_tool("cancel_reminder", {"content": "喝水"}, ctx(now))
    assert result.data["status"] == "ambiguous" and len(table) == 4
    assert [b.text for b in result.quick_replies] == ["取消提醒 1", "取消提醒 4"]


def test_cannot_cancel_another_chats_reminder(table, now):
    result = execute_tool("cancel_reminder", {"reminder_id": 1}, ctx(now, chat_id="U_other"))
    assert result.data["status"] == "not_found" and 1 in table


def test_management_tools_use_templates():
    from app.tools.base import should_rewrite
    assert not any(should_rewrite(name) for name in ("list_reminders", "mark_reminder_done", "cancel_reminder"))
