"""推播後的按鈕（喝了、30 分鐘後再提醒、今天不用了）與順便提醒"""
from datetime import time, timedelta

import pytest

import app.tools.reminders as reminders
from app.repositories.notification_repository import NotificationRecord
from app.services.reminder_schedule import Window, is_nudge_due, skip_today_run
from app.tools.base import ToolContext, run_action
from tests.conftest import taipei

DAYTIME = Window(time(9), time(21))


@pytest.fixture
def rows(monkeypatch):
    """記憶體中的提醒資料表"""
    table: dict[int, NotificationRecord] = {}

    def replace(id_, **changes):
        old = table[id_]
        table[id_] = NotificationRecord(**{**old.__dict__, **changes})

    def add(chat_id, message, run_at, repeat_daily, interval_minutes=None, window=None, nudge_interval_minutes=None):
        new_id = max(table, default=0) + 1
        table[new_id] = NotificationRecord(new_id, chat_id, message, repeat_daily, run_at, interval_minutes,
                                           window.start if window else None, window.end if window else None)
        return table[new_id]

    def record_reminded(id_, reminded_at, next_run_at, done=False):
        replace(id_, last_reminded_at=reminded_at, next_run_at=next_run_at, **({"last_done_at": reminded_at} if done else {}))

    monkeypatch.setattr(reminders, "get_notification", lambda id_: table.get(id_))
    monkeypatch.setattr(reminders, "add_scheduled_notification", add)
    monkeypatch.setattr(reminders, "record_reminded", record_reminded)
    monkeypatch.setattr(reminders, "reschedule_notification", lambda id_, run_at: replace(id_, next_run_at=run_at))
    monkeypatch.setattr(reminders, "get_recurring_notifications",
                        lambda chat_id: [r for r in table.values() if r.sender_id == chat_id and r.is_recurring])
    return table


def water(now, **changes):
    return NotificationRecord(**{
        "id": 1, "sender_id": "U1", "message": "喝水", "repeat_daily": False, "next_run_at": now + timedelta(hours=1),
        "interval_minutes": 180, "window_start": time(9), "window_end": time(21), **changes,
    })


def ctx(now, chat_id="U1"):
    return ToolContext(chat_id=chat_id, sender_id="U1", user_text="", now=now)


def press(record, label, now, chat_id="U1"):
    button = next(b for b in reminders.reminder_buttons(record) if b.label == label)
    return run_action(button.data, ctx(now, chat_id))


@pytest.mark.parametrize("content, label", [("喝水", "喝了 ✅"), ("吃藥", "吃了 ✅"), ("起來動一動", "做完了 ✅")])
def test_done_label(content, label):
    assert reminders.done_label(content) == label


def test_buttons_by_type(now):
    assert [b.label for b in reminders.reminder_buttons(water(now))] == ["喝了 ✅", "30 分鐘後再提醒", "今天不用了"]
    one_time = NotificationRecord(5, "U1", "開會", False, now)
    assert [b.label for b in reminders.reminder_buttons(one_time)] == ["30 分鐘後再提醒"]


def test_done_restarts_interval_from_now(rows, now):
    rows[1] = water(now)
    reply = press(rows[1], "喝了 ✅", now)
    assert rows[1].next_run_at == now + timedelta(hours=3)  # 從現在重新計算，原本 1 小時後的不提醒了
    assert rows[1].last_done_at == now and rows[1].last_reminded_at == now
    assert reply.fallback_text == "👍 讚！下次今天 17:30再提醒你喝水。"


def test_done_near_end_of_window_moves_to_tomorrow(rows):
    late = taipei(2026, 10, 20, 19, 0)
    rows[1] = water(late)
    press(rows[1], "喝了 ✅", late)
    assert rows[1].next_run_at == taipei(2026, 10, 21, 9, 0)


def test_snooze_recurring(rows, now):
    rows[1] = water(now)
    reply = press(rows[1], "30 分鐘後再提醒", now)
    assert rows[1].next_run_at == now + timedelta(minutes=30)
    assert "15:00再提醒你" in reply.fallback_text


def test_snooze_one_time_reminder_after_it_was_deleted(rows, now):
    sent = NotificationRecord(9, "U1", "關火：記得:檢查瓦斯", False, now)  # 內容含冒號也沒問題
    button_record = sent  # 推播時建立按鈕，之後資料庫裡的這筆就被刪除
    reply = press(button_record, "30 分鐘後再提醒", now)
    created = list(rows.values())
    assert len(created) == 1 and created[0].message == "關火：記得:檢查瓦斯"
    assert created[0].next_run_at == now + timedelta(minutes=30) and not created[0].is_recurring
    assert "再提醒你" in reply.fallback_text


def test_skip_today(rows, now):
    rows[1] = water(now)
    reply = press(rows[1], "今天不用了", now)
    assert rows[1].next_run_at == taipei(2026, 10, 21, 9, 0)
    assert reply.fallback_text == "好，今天先不提醒了，明天 09:00再開始。"


def test_buttons_from_another_chat_are_ignored(rows, now):
    rows[1] = water(now)
    original = rows[1].next_run_at
    assert "不存在" in press(rows[1], "喝了 ✅", now, chat_id="U_other").fallback_text
    assert rows[1].next_run_at == original


def test_deleted_recurring_reminder(rows, now):
    record = water(now)  # 不放進資料表：已被取消
    assert "不存在" in press(record, "喝了 ✅", now).fallback_text


# --- 順便提醒 ---

@pytest.mark.parametrize("last_reminded, hour, due", [
    ((13, 0), 14, True),    # 已過 1 小時（180 分的 1/3）
    ((13, 50), 14, False),  # 才 40 分鐘
    (None, 14, True),       # 沒提醒過：以上一個排定時間（next_run_at - 間隔）為準
    ((13, 0), 22, False),   # 時段外不提醒
])
def test_is_nudge_due(last_reminded, hour, due):
    now = taipei(2026, 10, 20, hour, 30)
    last = taipei(2026, 10, 20, *last_reminded) if last_reminded else None
    assert is_nudge_due(180, None, DAYTIME, taipei(2026, 10, 20, 16, 0), last, now) is due


def test_custom_nudge_interval_is_respected():
    now = taipei(2026, 10, 20, 14, 30)
    assert not is_nudge_due(180, 120, DAYTIME, now, taipei(2026, 10, 20, 13, 0), now)


def test_due_nudges_and_mark_nudged(rows, now):
    rows[1] = water(now, last_reminded_at=now - timedelta(hours=2))
    rows[2] = water(now, id=2, message="伸展", last_reminded_at=now - timedelta(minutes=10))
    due = reminders.due_nudges("U1", now)
    assert [r.message for r in due] == ["喝水"]
    reminders.mark_nudged(due[0], now)
    assert rows[1].last_reminded_at == now and rows[1].next_run_at == now + timedelta(hours=3)


def test_no_nudges_in_groups(rows, now):
    rows[1] = water(now, sender_id="C_group", last_reminded_at=now - timedelta(hours=2))
    assert reminders.due_nudges("C_group", now) == []


@pytest.mark.parametrize("window, hour, expected", [
    (DAYTIME, 14, (21, 9)),   # 時段內：今天剩下的都不提醒
    (DAYTIME, 7, (21, 9)),    # 今天的時段還沒開始：今天的也跳過
    (DAYTIME, 22, (21, 9)),   # 今天的時段已結束：明天照常
    (Window(time(22), time(2)), 23, (21, 22)),  # 跨午夜時段進行中：跳過今晚剩下的
    (Window(time(22), time(2)), 15, (21, 22)),  # 今晚的時段還沒開始：今晚也跳過
])
def test_skip_today_run(window, hour, expected):
    day, h = expected
    assert skip_today_run(180, window, taipei(2026, 10, 20, hour, 0)) == taipei(2026, 10, day, h, 0)


def test_skip_today_without_window():
    now = taipei(2026, 10, 20, 14, 0)
    assert skip_today_run(180, None, now) == now + timedelta(days=1)
