"""Alembic 執行環境。

- 服務啟動時由 app/db_migrations.py 傳入已上鎖的連線（config.attributes["connection"]）。
- 開發時用 CLI 執行，則依 DATABASE_URL 自行建立連線。
"""
from logging.config import fileConfig

from alembic import context
from sqlalchemy import create_engine, pool

from app.config import config as app_config
from app.models import load_all_models
from app.models.base import Base

alembic_config = context.config
if alembic_config.config_file_name and alembic_config.attributes.get("configure_logger", True):
    fileConfig(alembic_config.config_file_name, disable_existing_loggers=False)

load_all_models()
target_metadata = Base.metadata


def _configure(**kwargs):
    context.configure(
        target_metadata=target_metadata,
        compare_type=True,  # 欄位型別改變也要偵測到
        compare_server_default=True,  # 欄位預設值改變也要偵測到
        **kwargs,
    )


def run_migrations_offline() -> None:
    """只輸出 SQL（alembic upgrade head --sql），不連線。"""
    _configure(url=app_config.DATABASE_URL, literal_binds=True, dialect_opts={"paramstyle": "named"})
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connection = alembic_config.attributes.get("connection")
    if connection is not None:
        _configure(connection=connection)
        with context.begin_transaction():
            context.run_migrations()
        return

    if not app_config.DATABASE_URL:
        raise RuntimeError("請設定 DATABASE_URL 環境變數")
    engine = create_engine(app_config.DATABASE_URL, poolclass=pool.NullPool)
    with engine.connect() as connection:
        _configure(connection=connection)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
