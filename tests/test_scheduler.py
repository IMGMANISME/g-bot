from datetime import timedelta

import pytest

import app.schedule_notification as scheduler
from app.repositories.notification_repository import NotificationRecord


def record(id_, message, next_run_at, repeat_daily=False):
    return NotificationRecord(id_, f"C{id_}", message, next_run_at.time(), repeat_daily, next_run_at)


@pytest.fixture
def store(monkeypatch, now):
    """記憶體中的提醒資料表，並記錄推送"""
    state = {"rows": {}, "pushed": [], "fail": set()}

    def push(message, user_ids, image_url=None):
        state["pushed"].append(message)
        return not any(tag in message for tag in state["fail"])

    def reschedule(id_, next_run_at):
        old = state["rows"][id_]
        state["rows"][id_] = NotificationRecord(old.id, old.sender_id, old.message, old.time, old.repeat_daily, next_run_at)

    monkeypatch.setattr(scheduler, "try_acquire_job_lock", lambda *a, **k: True)
    monkeypatch.setattr(scheduler, "now_taipei", lambda: now)
    monkeypatch.setattr(scheduler, "push_line_message_to_users", push)
    monkeypatch.setattr(scheduler, "get_due_notifications",
                        lambda t: sorted((r for r in state["rows"].values() if r.next_run_at <= t), key=lambda r: r.next_run_at))
    monkeypatch.setattr(scheduler, "reschedule_notification", reschedule)
    monkeypatch.setattr(scheduler, "delete_notification", lambda id_: state["rows"].pop(id_))

    def add(r):
        state["rows"][r.id] = r

    state["add"] = add
    return state


def test_due_one_time_reminder_is_sent_and_deleted(store, now):
    store["add"](record(1, "開會", now - timedelta(seconds=30)))
    scheduler.check_and_send_notifications()
    assert store["pushed"] == ["⏰ 提醒你：開會"]
    assert 1 not in store["rows"]


def test_future_reminder_is_not_sent(store, now):
    store["add"](record(1, "晚點", now + timedelta(hours=1)))
    scheduler.check_and_send_notifications()
    assert store["pushed"] == [] and 1 in store["rows"]


def test_late_reminder_mentions_original_time(store, now):
    store["add"](record(1, "關火", now - timedelta(minutes=20)))
    scheduler.check_and_send_notifications()
    assert store["pushed"] == ["⏰ 提醒你：關火\n（原定 今天 14:10，延遲送達）"]


def test_daily_reminder_missed_for_days_is_sent_once(store, now):
    store["add"](record(1, "吃藥", now - timedelta(days=3, hours=6), repeat_daily=True))
    scheduler.check_and_send_notifications()
    assert store["pushed"] == ["⏰ 提醒你：吃藥\n（原定 今天 08:30，延遲送達）"]
    assert store["rows"][1].next_run_at == now - timedelta(hours=6) + timedelta(days=1)

    store["pushed"].clear()
    scheduler.check_and_send_notifications()
    assert store["pushed"] == []


def test_failed_push_is_retried_next_minute(store, now):
    store["fail"].add("重試")
    store["add"](record(1, "重試", now - timedelta(minutes=2)))
    scheduler.check_and_send_notifications()
    assert 1 in store["rows"]

    store["fail"].clear()
    scheduler.check_and_send_notifications()
    assert 1 not in store["rows"] and len(store["pushed"]) == 2


def test_failed_push_gives_up_after_window(store, now):
    store["fail"].add("放棄")
    store["add"](record(1, "放棄", now - timedelta(minutes=20)))
    store["add"](record(2, "放棄每日", now - timedelta(minutes=20), repeat_daily=True))
    scheduler.check_and_send_notifications()
    assert 1 not in store["rows"]
    assert store["rows"][2].next_run_at > now


def test_job_skipped_without_lock(store, now, monkeypatch):
    monkeypatch.setattr(scheduler, "try_acquire_job_lock", lambda *a, **k: False)
    store["add"](record(1, "開會", now - timedelta(seconds=30)))
    scheduler.check_and_send_notifications()
    assert store["pushed"] == []
