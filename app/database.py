# app/database.py
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import QueuePool
from contextlib import contextmanager

from app.config import config
from app.utils.logger import setup_logger

logger = setup_logger("database")

# 資料表結構由 Alembic migration 管理（app/migrations），啟動時由 app/db_migrations.py 升級

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
