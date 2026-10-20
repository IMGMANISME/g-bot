"""需要真的 PostgreSQL：設定 TEST_DATABASE_URL 才會執行（會清空並重建資料表）。

    TEST_DATABASE_URL=postgresql://user@localhost:5432/gbot_test pytest tests/test_database.py
"""
from datetime import timedelta

import pytest
from sqlalchemy import text

from tests.conftest import TEST_DATABASE_URL

pytestmark = pytest.mark.skipif(not TEST_DATABASE_URL, reason="未設定 TEST_DATABASE_URL，略過資料庫測試")


@pytest.fixture
def db():
    from app.database import engine, init_db
    from app.models.base import Base
    import app.models.notification  # noqa: F401  確保 metadata 已註冊

    with engine.begin() as connection:
        connection.execute(text("DROP SCHEMA public CASCADE; CREATE SCHEMA public;"))
        # 舊版的提醒表：沒有 next_run_at
        connection.execute(text(
            "CREATE TABLE scheduled_notifications (id SERIAL PRIMARY KEY, sender_id VARCHAR, message VARCHAR, "
            "time TIME, repeat_daily BOOLEAN, created_at TIMESTAMP)"
        ))
        connection.execute(text(
            "INSERT INTO scheduled_notifications (sender_id, message, time, repeat_daily) "
            "VALUES ('U_old', '舊的每日提醒', '08:00', true), ('U_old', '舊的一次提醒', '23:59', false)"
        ))
    init_db()
    yield engine
    Base.metadata.drop_all(bind=engine)


def test_old_reminders_are_migrated(db, now):
    from app.repositories.notification_repository import backfill_missing_next_run_at, get_user_notifications

    assert backfill_missing_next_run_at(now) == 2
    rows = {r.message: r for r in get_user_notifications("U_old")}
    assert rows["舊的每日提醒"].next_run_at.strftime("%m/%d %H:%M") == "10/21 08:00"
    assert rows["舊的一次提醒"].next_run_at.strftime("%m/%d %H:%M") == "10/20 23:59"
    assert backfill_missing_next_run_at(now) == 0


def test_due_reminders_and_reschedule(db, now):
    from app.repositories import notification_repository as repo

    due = repo.add_scheduled_notification("C1", "到了", now - timedelta(minutes=1), False)
    later = repo.add_scheduled_notification("C1", "還沒", now + timedelta(hours=1), True)
    assert [r.id for r in repo.get_due_notifications(now)] == [due.id]
    assert due.next_run_at.utcoffset() == timedelta(hours=8)  # 讀回來是台北時間

    repo.reschedule_notification(later.id, now - timedelta(seconds=1))
    assert {r.id for r in repo.get_due_notifications(now)} == {due.id, later.id}

    assert repo.delete_notification_by_id("C1", due.id) is True
    assert repo.delete_notification_by_id("C_other", later.id) is False  # 不能刪別人的
    assert [r.message for r in repo.get_user_notifications("C1")] == ["還沒"]


def test_job_lock(db):
    from app.repositories.system_state_repository import try_acquire_job_lock

    assert try_acquire_job_lock("test", ttl_seconds=60) is True
    assert try_acquire_job_lock("test", ttl_seconds=60) is False
