from datetime import datetime, time
from dataclasses import dataclass

from app.database import SessionLocal
from app.models.notification import ScheduledNotification
from app.services.reminder_schedule import Window, make_window
from app.utils.time_utils import to_taipei


@dataclass(frozen=True)
class NotificationRecord:
    id: int
    sender_id: str
    message: str
    repeat_daily: bool
    next_run_at: datetime  # 台北時間
    interval_minutes: int | None = None  # 週期提醒的間隔
    window_start: time | None = None
    window_end: time | None = None
    last_done_at: datetime | None = None
    nudge_interval_minutes: int | None = None
    last_reminded_at: datetime | None = None

    @property
    def is_recurring(self) -> bool:
        return bool(self.interval_minutes)

    @property
    def window(self) -> Window | None:
        return make_window(self.window_start, self.window_end)


def _to_record(notification: ScheduledNotification) -> NotificationRecord:
    return NotificationRecord(
        id=notification.id,
        sender_id=notification.sender_id,
        message=notification.message,
        repeat_daily=notification.repeat_daily,
        next_run_at=to_taipei(notification.next_run_at),
        interval_minutes=notification.interval_minutes,
        window_start=notification.window_start,
        window_end=notification.window_end,
        last_done_at=to_taipei(notification.last_done_at) if notification.last_done_at else None,
        nudge_interval_minutes=notification.nudge_interval_minutes,
        last_reminded_at=to_taipei(notification.last_reminded_at) if notification.last_reminded_at else None,
    )


def add_scheduled_notification(
    sender_id: str,
    message: str,
    run_at: datetime,
    repeat_daily: bool,
    interval_minutes: int | None = None,
    window: Window | None = None,
    nudge_interval_minutes: int | None = None,
) -> NotificationRecord:
    run_at = to_taipei(run_at)
    with SessionLocal() as db:
        notification = ScheduledNotification(
            sender_id=sender_id,
            message=message,
            repeat_daily=repeat_daily,
            next_run_at=run_at,
            interval_minutes=interval_minutes,
            window_start=window.start if window else None,
            window_end=window.end if window else None,
            nudge_interval_minutes=nudge_interval_minutes,
        )
        db.add(notification)
        db.commit()
        db.refresh(notification)
        return _to_record(notification)

def get_due_notifications(now: datetime) -> list[NotificationRecord]:
    """取得已到時間但尚未送出的提醒（包含排程器漏跑而延遲的）。"""
    with SessionLocal() as db:
        notifications = (
            db.query(ScheduledNotification)
            .filter(ScheduledNotification.next_run_at <= now)
            .order_by(ScheduledNotification.next_run_at.asc())
            .all()
        )
        return [_to_record(notification) for notification in notifications]

def reschedule_notification(notification_id: int, next_run_at: datetime):
    with SessionLocal() as db:
        db.query(ScheduledNotification).filter_by(id=notification_id).update({"next_run_at": next_run_at})
        db.commit()

def delete_notification(notification_id: int):
    with SessionLocal() as db:
        db.query(ScheduledNotification).filter_by(id=notification_id).delete()
        db.commit()

def get_user_notifications(sender_id: str):
    with SessionLocal() as db:
        notifications = (
            db.query(ScheduledNotification)
            .filter(ScheduledNotification.sender_id == sender_id)
            .order_by(ScheduledNotification.next_run_at.asc())
            .all()
        )
        return [_to_record(notification) for notification in notifications]

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


def get_notification(notification_id: int) -> NotificationRecord | None:
    with SessionLocal() as db:
        notification = db.query(ScheduledNotification).filter_by(id=notification_id).first()
        return _to_record(notification) if notification else None


def get_recurring_notifications(sender_id: str) -> list[NotificationRecord]:
    with SessionLocal() as db:
        notifications = (
            db.query(ScheduledNotification)
            .filter(ScheduledNotification.sender_id == sender_id, ScheduledNotification.interval_minutes.isnot(None))
            .order_by(ScheduledNotification.next_run_at.asc())
            .all()
        )
        return [_to_record(notification) for notification in notifications]


def record_reminded(notification_id: int, reminded_at: datetime, next_run_at: datetime, done: bool = False):
    """推播、順便提醒或使用者回報完成後：記下時間並排定下一次"""
    values = {"last_reminded_at": reminded_at, "next_run_at": next_run_at}
    if done:
        values["last_done_at"] = reminded_at
    with SessionLocal() as db:
        db.query(ScheduledNotification).filter_by(id=notification_id).update(values)
        db.commit()
