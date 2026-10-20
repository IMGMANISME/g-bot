from sqlalchemy import Column, String, Integer, DateTime, Boolean
from datetime import datetime
from app.models.base import Base

class ScheduledNotification(Base):
    __tablename__ = "scheduled_notifications"
    id = Column(Integer, primary_key=True, autoincrement=True)
    sender_id = Column(String, index=True)  # 聊天室 ID
    message = Column(String)
    repeat_daily = Column(Boolean, nullable=False, default=False)
    next_run_at = Column(DateTime(timezone=True), nullable=False, index=True)  # 下一次要送出的時間
    created_at = Column(DateTime, default=datetime.utcnow)
