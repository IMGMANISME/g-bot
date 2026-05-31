# app/database.py
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import QueuePool
from contextlib import contextmanager
from importlib import import_module

from app.config import config
from app.utils.logger import setup_logger
from app.utils.decorators import handle_exceptions

logger = setup_logger("database")

COMPAT_COLUMNS = {
    "user_state": {
        "earthquake_enabled": "BOOLEAN DEFAULT TRUE",
        "earthquake_min_magnitude": "FLOAT",
    }
}

# 建立資料庫引擎，使用連接池
engine = create_engine(
    config.DATABASE_URL,
    pool_pre_ping=True,  # 檢查連接是否有效
    poolclass=QueuePool,
    pool_size=config.DB_POOL_SIZE,          # 連接池大小
    max_overflow=config.DB_MAX_OVERFLOW,    # 最大溢出連接數
    pool_recycle=config.DB_POOL_RECYCLE,    # 連接回收時間（秒）
    pool_timeout=config.DB_POOL_TIMEOUT,    # 取得連接的超時時間
    echo=False           # 設為 True 可顯示 SQL 語句
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

@contextmanager
def get_db_session():
    """取得資料庫會話的上下文管理器"""
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception as e:
        session.rollback()
        logger.error(f"資料庫操作失敗: {e}")
        raise
    finally:
        session.close()

@handle_exceptions("資料庫初始化失敗")
def init_db():
    """初始化資料庫"""
    from app.models.base import Base
    # 匯入模型模組以確保 SQLAlchemy metadata 完整註冊
    model_modules = [
        "app.models.user",
        "app.models.message",
        "app.models.restaurant",
        "app.models.notification",
        "app.models.system_state",
    ]
    for module in model_modules:
        import_module(module)
    
    try:
        Base.metadata.create_all(bind=engine)
        _ensure_compat_columns()
        logger.info("✅ 資料庫表格建立成功")
    except Exception as e:
        logger.error(f"❌ 資料庫初始化失敗: {e}")
        raise

def _ensure_compat_columns():
    """Add simple backward-compatible columns when no migration tool is present."""
    inspector = inspect(engine)
    with engine.begin() as connection:
        for table_name, columns in COMPAT_COLUMNS.items():
            if not inspector.has_table(table_name):
                continue
            existing_columns = {column["name"] for column in inspector.get_columns(table_name)}
            for column_name, column_type in columns.items():
                if column_name in existing_columns:
                    continue
                connection.execute(text(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_type}"))
                logger.info(f"已新增相容欄位: {table_name}.{column_name}")
