from datetime import datetime
from typing import Optional, Tuple
from app.database import SessionLocal
from app.models.user import UserState, UserLocation, UserProfile
from app.utils.logger import setup_logger

logger = setup_logger("user_repository")

def set_silent(sender_id: str):
    with SessionLocal() as db:
        state = db.query(UserState).filter_by(sender_id=sender_id).first()
        if not state:
            state = UserState(sender_id=sender_id, is_silent=1)
            db.add(state)
        else:
            state.is_silent = 1
        db.commit()

def clear_silent(sender_id: str):
    with SessionLocal() as db:
        state = db.query(UserState).filter_by(sender_id=sender_id).first()
        if state:
            state.is_silent = 0
            db.commit()

def is_silent(sender_id: str) -> bool:
    with SessionLocal() as db:
        state = db.query(UserState).filter_by(sender_id=sender_id).first()
        return state.is_silent == 1 if state else False

def set_mention_mode(sender_id: str, enabled: bool):
    with SessionLocal() as db:
        state = db.query(UserState).filter_by(sender_id=sender_id).first()
        if not state:
            state = UserState(sender_id=sender_id)
            db.add(state)
        state.mention_mode = enabled
        db.commit()

def is_mention_mode(sender_id: str) -> bool:
    with SessionLocal() as db:
        state = db.query(UserState).filter_by(sender_id=sender_id).first()
        return state.mention_mode if state else False

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
    with SessionLocal() as db:
        location = db.query(UserLocation).filter_by(sender_id=sender_id).first()
        if not location:
            location = UserLocation(sender_id=sender_id, latitude=str(lat), longitude=str(lng))
            db.add(location)
        else:
            location.latitude = str(lat)
            location.longitude = str(lng)
            location.updated_at = datetime.utcnow()
        db.commit()

def get_user_location(sender_id: str) -> Optional[Tuple[float, float]]:
    with SessionLocal() as db:
        location = db.query(UserLocation).filter_by(sender_id=sender_id).first()
        if location:
            return float(location.latitude), float(location.longitude)
        return None

def upsert_user_profile(sender_id: str, display_name: str, picture_url: str = None):
    with SessionLocal() as db:
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
            db.rollback()
            logger.error(f"更新用戶資料失敗: {e}")

def get_cached_user_profile(sender_id: str) -> Optional[dict]:
    with SessionLocal() as db:
        profile = db.query(UserProfile).filter_by(sender_id=sender_id).first()
        if profile:
            return {
                "display_name": profile.display_name,
                "picture_url": profile.picture_url,
                "updated_at": profile.updated_at
            }
        return None
