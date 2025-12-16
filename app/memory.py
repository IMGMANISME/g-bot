#app/memory.py
from sqlalchemy import create_engine, Column, String, Text, DateTime, Integer, Boolean, Time, func
from sqlalchemy.orm import declarative_base, sessionmaker
from sqlalchemy.pool import QueuePool
from datetime import datetime
from datetime import time as dtime
from contextlib import contextmanager
from typing import List, Optional, Tuple
import os
import math

from app.config import config
from app.utils.logger import setup_logger
from app.utils.decorators import handle_exceptions

logger = setup_logger("memory")

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
Base = declarative_base()

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

class Message(Base):
    __tablename__ = "memory"
    id = Column(Integer, primary_key=True, autoincrement=True)
    sender_id = Column(String)
    role = Column(String)
    content = Column(Text)
    timestamp = Column(DateTime, default=datetime.utcnow)

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

class Restaurant(Base):
    __tablename__ = "restaurants"
    place_id = Column(String, primary_key=True)
    name = Column(String, nullable=False)
    address = Column(String)
    rating = Column(Integer)
    price_level = Column(Integer)
    lat = Column(String)
    lng = Column(String)
    saved_at = Column(DateTime, default=datetime.utcnow)

class ScheduledNotification(Base):
    __tablename__ = "scheduled_notifications"
    id = Column(Integer, primary_key=True, autoincrement=True)
    sender_id = Column(String, index=True)
    message = Column(String)
    time = Column(Time)
    repeat_daily = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)

@handle_exceptions("資料庫初始化失敗")
def init_db():
    """初始化資料庫"""
    try:
        Base.metadata.create_all(bind=engine)
        logger.info("✅ 資料庫表格建立成功")
    except Exception as e:
        logger.error(f"❌ 資料庫初始化失敗: {e}")
        raise

@handle_exceptions("訊息儲存失敗")
def save_message(sender_id: str, role: str, content: str):
    """儲存訊息並保持最新10條記錄"""
    try:
        with get_db_session() as session:
            message = Message(sender_id=sender_id, role=role, content=content)
            session.add(message)
            session.flush()  # 確保訊息已保存
            
            # 清理舊訊息，只保留最新10條
            old_messages = session.query(Message).filter(
                Message.sender_id == sender_id
            ).order_by(Message.timestamp.desc()).offset(10).all()
            
            for msg in old_messages:
                session.delete(msg)
            
            logger.debug(f"為用戶 {sender_id} 儲存訊息，清理了 {len(old_messages)} 條舊記錄")
    except Exception as e:
        logger.error(f"儲存訊息失敗: {e}")

@handle_exceptions("訊息歷史取得失敗", reraise=False)
def get_history(sender_id: str) -> List[dict]:
    """取得對話歷史"""
    try:
        with get_db_session() as session:
            messages = session.query(Message).filter(
                Message.sender_id == sender_id
            ).order_by(Message.timestamp.asc()).all()
            
            return [{"role": m.role, "content": m.content} for m in messages]
    except Exception as e:
        logger.error(f"取得歷史記錄失敗: {e}")
        return []

@handle_exceptions("清除歷史失敗")
def clear_history(sender_id: str):
    """清除對話歷史"""
    try:
        with get_db_session() as session:
            deleted_count = session.query(Message).filter(
                Message.sender_id == sender_id
            ).delete()
            logger.info(f"清除了用戶 {sender_id} 的 {deleted_count} 條歷史記錄")
    except Exception as e:
        logger.error(f"清除歷史失敗: {e}")

def set_silent(sender_id: str):
    db = SessionLocal()
    try:
        state = db.query(UserState).filter_by(sender_id=sender_id).first()
        if not state:
            state = UserState(sender_id=sender_id, is_silent=1)
            db.add(state)
        else:
            state.is_silent = 1
        db.commit()
    finally:
        db.close()

def clear_silent(sender_id: str):
    db = SessionLocal()
    try:
        state = db.query(UserState).filter_by(sender_id=sender_id).first()
        if state:
            state.is_silent = 0
            db.commit()
    finally:
        db.close()

def is_silent(sender_id: str) -> bool:
    db = SessionLocal()
    try:
        state = db.query(UserState).filter_by(sender_id=sender_id).first()
        return state.is_silent == 1 if state else False
    finally:
        db.close()

def set_mention_mode(sender_id: str, enabled: bool):
    db = SessionLocal()
    try:
        state = db.query(UserState).filter_by(sender_id=sender_id).first()
        if not state:
            state = UserState(sender_id=sender_id)
            db.add(state)
        state.mention_mode = enabled
        db.commit()
    finally:
        db.close()

def is_mention_mode(sender_id: str) -> bool:
    db = SessionLocal()
    try:
        state = db.query(UserState).filter_by(sender_id=sender_id).first()
        return state.mention_mode if state else False
    finally:
        db.close()

def get_user_state(sender_id: str) -> str:
    silent = is_silent(sender_id)
    mention = is_mention_mode(sender_id)
    
    if silent and mention:
        return "silent_mention"
    elif silent and not mention:
        return "silent_active"
    elif not silent and mention:
        return "active_mention"
    return "active"

def set_user_state(sender_id: str, state: str):
    if state == "silent":
        set_silent(sender_id)
    else:
        clear_silent(sender_id)

    if state == "mention_only":
        set_mention_mode(sender_id, True)
    else:
        set_mention_mode(sender_id, False)

def upsert_user_location(sender_id: str, lat: float, lng: float):
    db = SessionLocal()
    try:
        location = db.query(UserLocation).filter_by(sender_id=sender_id).first()
        if not location:
            location = UserLocation(sender_id=sender_id, latitude=str(lat), longitude=str(lng))
            db.add(location)
        else:
            location.latitude = str(lat)
            location.longitude = str(lng)
            location.updated_at = datetime.utcnow()
        db.commit()
    finally:
        db.close()

def get_user_location(sender_id: str):
    db = SessionLocal()
    try:
        location = db.query(UserLocation).filter_by(sender_id=sender_id).first()
        if location:
            return float(location.latitude), float(location.longitude)
        return None
    finally:
        db.close()

def upsert_user_profile(sender_id: str, display_name: str, picture_url: str = None):
    """更新或插入用戶個人資料"""
    db = SessionLocal()
    try:
        profile = db.query(UserProfile).filter_by(sender_id=sender_id).first()
        if not profile:
            profile = UserProfile(
                sender_id=sender_id,
                display_name=display_name,
                picture_url=picture_url
            )
            db.add(profile)
        else:
            profile.display_name = display_name
            if picture_url:
                profile.picture_url = picture_url
        db.commit()
    except Exception as e:
        logger.error(f"更新用戶資料失敗: {e}")
    finally:
        db.close()

def get_cached_user_profile(sender_id: str) -> Optional[dict]:
    """取得快取的用戶個人資料"""
    db = SessionLocal()
    try:
        profile = db.query(UserProfile).filter_by(sender_id=sender_id).first()
        if profile:
            return {
                "display_name": profile.display_name,
                "picture_url": profile.picture_url,
                "updated_at": profile.updated_at
            }
        return None
    finally:
        db.close()

def save_restaurant(place: dict, lat: float, lng: float):
    db = SessionLocal()
    try:
        if not place.get("place_id"):
            return
        existing = db.query(Restaurant).filter_by(place_id=place["place_id"]).first()
        if not existing:
            restaurant = Restaurant(
                place_id=place["place_id"],
                name=place.get("name"),
                address=place.get("vicinity"),
                rating=place.get("rating"),
                price_level=place.get("price_level"),
                lat=str(lat),
                lng=str(lng),
            )
            db.add(restaurant)
            db.commit()
    finally:
        db.close()

def get_restaurants_backup(lat: float, lng: float, radius=4000, min_price=0, max_price=4, min_rating=3.5, limit=5):
    db = SessionLocal()
    try:
        lat_diff = radius / 111000
        lng_diff = radius / (111000 * abs(math.cos(math.radians(lat))) + 0.00001)
        results = db.query(Restaurant)\
            .filter(Restaurant.lat.between(str(lat - lat_diff), str(lat + lat_diff)))\
            .filter(Restaurant.lng.between(str(lng - lng_diff), str(lng + lng_diff)))\
            .filter(Restaurant.rating >= min_rating)\
            .filter(Restaurant.price_level >= min_price, Restaurant.price_level <= max_price)\
            .order_by(func.random())\
            .limit(limit)\
            .all()
        return results
    finally:
        db.close()

def add_scheduled_notification(sender_id: str, message: str, time_str: str, repeat_daily: bool):
    db = SessionLocal()
    try:
        hh, mm = map(int, time_str.split(":"))
        notification = ScheduledNotification(
            sender_id=sender_id,
            message=message,
            time=dtime(hh, mm),
            repeat_daily=repeat_daily
        )
        db.add(notification)
        db.commit()
    finally:
        db.close()

def get_notifications_to_send(current_time: dtime):
    db = SessionLocal()
    try:
        return db.query(ScheduledNotification).filter(ScheduledNotification.time == current_time).all()
    finally:
        db.close()

def delete_notification(notification_id: int):
    db = SessionLocal()
    try:
        db.query(ScheduledNotification).filter_by(id=notification_id).delete()
        db.commit()
    finally:
        db.close()

def get_user_notifications(sender_id: str):
    db = SessionLocal()
    try:
        return db.query(ScheduledNotification).filter(ScheduledNotification.sender_id == sender_id).order_by(ScheduledNotification.time.asc()).all()
    finally:
        db.close()

def delete_notification_by_id(sender_id: str, notification_id: int) -> bool:
    db = SessionLocal()
    try:
        notification = db.query(ScheduledNotification).filter_by(id=notification_id, sender_id=sender_id).first()
        if notification:
            db.delete(notification)
            db.commit()
            return True
        return False
    finally:
        db.close()

def delete_all_notifications_for_sender(sender_id: str) -> int:
    db = SessionLocal()
    try:
        count = db.query(ScheduledNotification).filter_by(sender_id=sender_id).delete()
        db.commit()
        return count
    finally:
        db.close()

def delete_all_notifications_for_user(sender_id: str) -> int:
    return delete_all_notifications_for_sender(sender_id)