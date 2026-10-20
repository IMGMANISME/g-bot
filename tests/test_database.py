"""需要真的 PostgreSQL：設定 TEST_DATABASE_URL 才會執行（會清空並重建資料表）。

    TEST_DATABASE_URL=postgresql://user@localhost:5432/gbot_test pytest tests/test_database.py
"""
from datetime import timedelta

import pytest
from sqlalchemy import inspect, text

from tests.conftest import TEST_DATABASE_URL

pytestmark = pytest.mark.skipif(not TEST_DATABASE_URL, reason="未設定 TEST_DATABASE_URL，略過資料庫測試")


def _reset_schema(engine):
    with engine.begin() as connection:
        connection.execute(text("DROP SCHEMA public CASCADE; CREATE SCHEMA public;"))


@pytest.fixture
def empty_db():
    from app.database import engine
    _reset_schema(engine)
    yield engine
    _reset_schema(engine)


@pytest.fixture
def db(empty_db):
    from app.db_migrations import upgrade_database
    upgrade_database()
    return empty_db


# --- migration ---

def test_upgrade_creates_all_tables_at_head(db):
    from app.db_migrations import head_revision
    tables = set(inspect(db).get_table_names())
    assert {"user_state", "user_locations", "user_profiles", "memory", "scheduled_notifications",
            "restaurants", "system_state", "alembic_version"} <= tables
    with db.connect() as connection:
        assert connection.execute(text("SELECT version_num FROM alembic_version")).scalar() == head_revision()


def test_models_match_migrations(db):
    """改了 model 卻沒寫 migration 時會失敗：請執行 alembic revision --autogenerate"""
    from alembic.autogenerate import compare_metadata
    from alembic.runtime.migration import MigrationContext
    from app.models import load_all_models
    from app.models.base import Base

    load_all_models()
    with db.connect() as connection:
        context = MigrationContext.configure(connection, opts={"compare_type": True, "compare_server_default": True})
        assert compare_metadata(context, Base.metadata) == []


def test_upgrade_is_idempotent(db):
    from app.db_migrations import upgrade_database
    upgrade_database()  # 已是最新版本，不應出錯


def test_legacy_database_is_refused_and_left_untouched(empty_db):
    from app.db_migrations import LegacyDatabaseError, upgrade_database
    with empty_db.begin() as connection:
        connection.execute(text("CREATE TABLE user_state (sender_id VARCHAR PRIMARY KEY, is_silent INTEGER)"))
        connection.execute(text("INSERT INTO user_state VALUES ('U1', 1)"))

    with pytest.raises(LegacyDatabaseError, match="請先清空資料庫"):
        upgrade_database()

    with empty_db.connect() as connection:
        assert connection.execute(text("SELECT count(*) FROM user_state")).scalar() == 1
    assert "alembic_version" not in inspect(empty_db).get_table_names()


# --- repositories ---

def test_reminders(db, now):
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


def test_user_state_defaults_and_modes(db):
    from app.repositories import user_repository as repo

    assert repo.get_user_state("C1") == "active"
    assert repo.get_earthquake_settings("C1") == {"enabled": False, "min_magnitude": None}
    repo.set_user_state("C1", "silent_mention")
    assert repo.get_user_state("C1") == "silent_mention"
    repo.set_user_state("C1", "active")
    assert repo.get_user_state("C1") == "active"

    # 直接用 SQL 新增也有預設值（server default）
    with db.begin() as connection:
        connection.execute(text("INSERT INTO user_state (sender_id) VALUES ('C2')"))
    assert repo.get_user_state("C2") == "active"


def test_location_is_stored_as_numbers(db):
    from app.repositories import user_repository as repo

    repo.upsert_user_location("U1", 25.033964, 121.564468)
    assert repo.get_user_location("U1") == (25.033964, 121.564468)
    repo.upsert_user_location("U1", 22.6273, 120.3014)
    assert repo.get_user_location("U1") == (22.6273, 120.3014)


def test_restaurant_backup_query(db):
    from app.repositories.restaurant_repository import get_restaurants_backup, save_restaurant

    def place(pid, dlat, rating, price):
        return {"place_id": pid, "name": pid, "vicinity": "地址", "rating": rating, "price_level": price,
                "geometry": {"location": {"lat": 25.0 + dlat, "lng": 121.5}}}

    save_restaurant(place("near", 0.001, 4.6, 1), 25.0, 121.5)
    save_restaurant(place("far", 0.1, 4.9, 1), 25.0, 121.5)
    save_restaurant(place("low", 0.002, 3.2, 1), 25.0, 121.5)
    results = get_restaurants_backup(25.0, 121.5, radius=1000, min_rating=3.5)
    assert [r.place_id for r in results] == ["near"]
    assert results[0].rating == 4.6  # 評分保留小數


def test_job_lock(db):
    from app.repositories.system_state_repository import try_acquire_job_lock

    assert try_acquire_job_lock("test", ttl_seconds=60) is True
    assert try_acquire_job_lock("test", ttl_seconds=60) is False


def test_earthquake_recipients(db):
    from app.repositories import user_repository as repo

    repo.get_user_state("C_default")  # 建立預設設定：沒開地震通知
    repo.set_earthquake_subscription("C_on", True)
    repo.set_earthquake_min_magnitude("C_high", 5.5)  # 設門檻也會順便開啟
    repo.set_earthquake_subscription("C_off", False)

    assert sorted(repo.get_earthquake_recipient_ids(4.5, default_min_magnitude=4.0)) == ["C_on"]
    assert sorted(repo.get_earthquake_recipient_ids(6.0, default_min_magnitude=4.0)) == ["C_high", "C_on"]
    assert repo.get_earthquake_recipient_ids(3.0, default_min_magnitude=4.0) == []


def test_migration_0002_turns_existing_alerts_off(empty_db):
    """0001 時代的聊天室預設是開啟的，升級到 0002 後一律關閉，新聊天室也預設關閉"""
    from alembic import command
    from app.db_migrations import alembic_config, upgrade_database

    cfg = alembic_config()
    with empty_db.begin() as connection:
        cfg.attributes["connection"] = connection
        command.upgrade(cfg, "0001")
        connection.execute(text("INSERT INTO user_state (sender_id) VALUES ('C_old')"))
        assert connection.execute(text("SELECT earthquake_enabled FROM user_state")).scalar() is True

    upgrade_database()
    with empty_db.begin() as connection:
        assert connection.execute(text("SELECT earthquake_enabled FROM user_state WHERE sender_id = 'C_old'")).scalar() is False
        connection.execute(text("INSERT INTO user_state (sender_id) VALUES ('C_new')"))
        assert connection.execute(text("SELECT earthquake_enabled FROM user_state WHERE sender_id = 'C_new'")).scalar() is False


def test_recurring_reminder_roundtrip(db, now):
    from datetime import time
    from app.repositories import notification_repository as repo
    from app.services.reminder_schedule import Window

    created = repo.add_scheduled_notification("U1", "喝水", now + timedelta(hours=2), False, 120, Window(time(22), time(2)))
    loaded = repo.get_user_notifications("U1")[0]
    assert loaded.id == created.id and loaded.is_recurring
    assert (loaded.interval_minutes, loaded.window) == (120, Window(time(22), time(2)))
    assert loaded.last_done_at is None
