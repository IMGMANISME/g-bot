from datetime import datetime
from sqlalchemy import Column, DateTime, String, Text

from app.models.base import Base


class SystemState(Base):
    __tablename__ = "system_state"

    key = Column(String, primary_key=True)
    value = Column(Text)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
