from sqlalchemy import Column, String, Text, DateTime, Integer
from datetime import datetime
from app.models.base import Base

class Message(Base):
    __tablename__ = "memory"
    id = Column(Integer, primary_key=True, autoincrement=True)
    sender_id = Column(String)
    role = Column(String)
    content = Column(Text)
    timestamp = Column(DateTime, default=datetime.utcnow)
