from sqlalchemy import Column, String, Integer, DateTime, Boolean, Time
from datetime import datetime
from app.models.base import Base

class ScheduledNotification(Base):
    __tablename__ = "scheduled_notifications"
    id = Column(Integer, primary_key=True, autoincrement=True)
    sender_id = Column(String, index=True)
    message = Column(String)
    time = Column(Time)
    repeat_daily = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
