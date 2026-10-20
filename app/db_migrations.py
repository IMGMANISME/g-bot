# app/db_migrations.py
"""啟動時把資料庫升級到最新的 migration。

- 資料庫是空的，或已由 Alembic 管理：執行尚未套用的 migration。
- 有資料表但沒有 Alembic 版本紀錄（舊版用 create_all 建立的）：停止啟動並說明要先清空。
  這裡絕對不會自己刪除資料表。
"""
from pathlib import Path

from alembic import command
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import inspect, text

from app.database import engine
from app.utils.logger import setup_logger

logger = setup_logger("db_migrations")

MIGRATIONS_DIR = Path(__file__).resolve().parent / "migrations"
# 固定的鎖編號：同時有多個程序啟動時，一次只讓一個跑 migration
MIGRATION_LOCK_ID = 7_265_103


class LegacyDatabaseError(RuntimeError):
    """資料庫是舊版結構，需要先清空才能交給 Alembic 管理。"""


def alembic_config() -> Config:
    cfg = Config()
    cfg.set_main_option("script_location", str(MIGRATIONS_DIR))
    cfg.attributes["configure_logger"] = False  # 沿用 app 的 logger 設定
    return cfg


def head_revision() -> str:
    return ScriptDirectory.from_config(alembic_config()).get_current_head()


def upgrade_database() -> None:
    cfg = alembic_config()
    with engine.begin() as connection:
        # 交易結束時自動釋放
        connection.execute(text("SELECT pg_advisory_xact_lock(:lock_id)"), {"lock_id": MIGRATION_LOCK_ID})

        current = MigrationContext.configure(connection).get_current_revision()
        tables = set(inspect(connection).get_table_names()) - {"alembic_version"}
        if current is None and tables:
            raise LegacyDatabaseError(
                "資料庫已有資料表但不是由 Alembic 建立（舊版結構："
                f"{', '.join(sorted(tables))}）。請先清空資料庫再重新部署，"
                "例如執行：DROP SCHEMA public CASCADE; CREATE SCHEMA public;"
            )

        head = head_revision()
        if current == head:
            logger.info(f"資料庫已是最新版本: {head}")
            return

        logger.info(f"資料庫升級: {current or '空資料庫'} → {head}")
        cfg.attributes["connection"] = connection
        command.upgrade(cfg, "head")
        logger.info("✅ 資料庫升級完成")
