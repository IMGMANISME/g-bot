# app/database.py
from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker
from sqlalchemy.pool import QueuePool
from contextlib import contextmanager

from app.config import config
from app.utils.logger import setup_logger
from app.utils.decorators import handle_exceptions

logger = setup_logger("database")

# 建立資料庫引擎，使用連接池
engine = create_engine(
    config.DATABASE_URL,
    pool_pre_ping=True,  # 檢查連接是否有效
    poolclass=QueuePool,
    pool_size=10,        # 連接池大小
    max_overflow=20,     # 最大溢出連接數
    pool_recycle=3600,   # 連接回收時間（秒）
    pool_timeout=30,     # 取得連接的超時時間
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
    # import all models before creating to ensure they are registered
    import app.models.user
    import app.models.message
    import app.models.restaurant
    import app.models.notification
    
    try:
        Base.metadata.create_all(bind=engine)
        logger.info("✅ 資料庫表格建立成功")
    except Exception as e:
        logger.error(f"❌ 資料庫初始化失敗: {e}")
        raise
