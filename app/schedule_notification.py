#app/schedule_notification.py
import asyncio
from datetime import datetime, time as dtime
from pytz import timezone

from app.memory import get_notifications_to_send, delete_notification
from app.line_bot import push_line_message_to_users


async def check_and_send_notifications():
    tz = timezone("Asia/Taipei")
    now = datetime.now(tz).time().replace(second=0, microsecond=0)
    tasks = get_notifications_to_send(now)

    for task in tasks:
        push_line_message_to_users(task.message, [task.sender_id])
        if not task.repeat_daily:
            delete_notification(task.id)


async def start_notifications_scheduler():
    print("✅ Async Notifications Scheduler started.")
    while True:
        await check_and_send_notifications()
        
        # 等待直到下個整點分鐘（如 12:01, 12:02...）
        now = datetime.now()
        next_minute = now.replace(second=0, microsecond=0)
        next_minute = next_minute.replace(minute=now.minute + 1 if now.minute < 59 else 0)
        if now.minute == 59:
            next_minute = next_minute.replace(hour=(now.hour + 1) % 24)

        wait_seconds = (next_minute - now).total_seconds()
        await asyncio.sleep(wait_seconds)