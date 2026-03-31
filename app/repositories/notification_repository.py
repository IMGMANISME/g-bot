from datetime import time as dtime
from app.database import SessionLocal
from app.models.notification import ScheduledNotification

def add_scheduled_notification(sender_id: str, message: str, time_str: str, repeat_daily: bool):
    with SessionLocal() as db:
        hh, mm = map(int, time_str.split(":"))
        notification = ScheduledNotification(
            sender_id=sender_id,
            message=message,
            time=dtime(hh, mm),
            repeat_daily=repeat_daily
        )
        db.add(notification)
        db.commit()

def get_notifications_to_send(current_time: dtime):
    with SessionLocal() as db:
        return db.query(ScheduledNotification).filter(ScheduledNotification.time == current_time).all()

def delete_notification(notification_id: int):
    with SessionLocal() as db:
        db.query(ScheduledNotification).filter_by(id=notification_id).delete()
        db.commit()

def get_user_notifications(sender_id: str):
    with SessionLocal() as db:
        return db.query(ScheduledNotification).filter(ScheduledNotification.sender_id == sender_id).order_by(ScheduledNotification.time.asc()).all()

def delete_notification_by_id(sender_id: str, notification_id: int) -> bool:
    with SessionLocal() as db:
        notification = db.query(ScheduledNotification).filter_by(id=notification_id, sender_id=sender_id).first()
        if notification:
            db.delete(notification)
            db.commit()
            return True
        return False

def delete_all_notifications_for_sender(sender_id: str) -> int:
    with SessionLocal() as db:
        count = db.query(ScheduledNotification).filter_by(sender_id=sender_id).delete()
        db.commit()
        return count

def delete_all_notifications_for_user(sender_id: str) -> int:
    return delete_all_notifications_for_sender(sender_id)
