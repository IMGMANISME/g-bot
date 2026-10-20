from sqlalchemy import Column, String, DateTime, Boolean, Float, false
from datetime import datetime
from app.models.base import Base

class UserState(Base):
    """聊天室設定（sender_id 欄位存的是聊天室 ID：一對一為 user ID，群組為 group ID）"""
    __tablename__ = "user_state"
    sender_id = Column(String, primary_key=True)
    is_silent = Column(Boolean, nullable=False, default=False, server_default=false())
    mention_mode = Column(Boolean, nullable=False, default=False, server_default=false())
    earthquake_enabled = Column(Boolean, nullable=False, default=False, server_default=false())  # 預設關閉，要自己開
    earthquake_min_magnitude = Column(Float, nullable=True)

class UserLocation(Base):
    __tablename__ = "user_locations"
    sender_id = Column(String, primary_key=True)
    latitude = Column(Float, nullable=False)
    longitude = Column(Float, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow)

class UserProfile(Base):
    __tablename__ = "user_profiles"
    sender_id = Column(String, primary_key=True)
    display_name = Column(String)
    picture_url = Column(String)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
