from sqlalchemy import Column, String, DateTime, Integer, Boolean
from datetime import datetime
from app.models.base import Base

class UserState(Base):
    __tablename__ = "user_state"
    sender_id = Column(String, primary_key=True)
    is_silent = Column(Integer, default=0)
    mention_mode = Column(Boolean, default=False)

class UserLocation(Base):
    __tablename__ = "user_locations"
    sender_id = Column(String, primary_key=True)
    latitude = Column(String)
    longitude = Column(String)
    updated_at = Column(DateTime, default=datetime.utcnow)

class UserProfile(Base):
    __tablename__ = "user_profiles"
    sender_id = Column(String, primary_key=True)
    display_name = Column(String)
    picture_url = Column(String)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
