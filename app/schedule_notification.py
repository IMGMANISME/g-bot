#app/schedule_notification.py
from datetime import datetime
from pytz import timezone
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from app.repositories.notification_repository import get_notifications_to_send, delete_notification
from app.repositories.system_state_repository import try_acquire_job_lock
from app.utils.line_utils import push_line_message_to_users
from app.utils.logger import setup_logger

logger = setup_logger("scheduler")
scheduler = AsyncIOScheduler(timezone=timezone("Asia/Taipei"))

async def check_and_send_notifications():
    try:
        if not try_acquire_job_lock("notifications", ttl_seconds=55):
            return

        tz = timezone("Asia/Taipei")
        now = datetime.now(tz).time().replace(second=0, microsecond=0)
        tasks = get_notifications_to_send(now)

        if tasks:
            logger.info(f"發現 {len(tasks)} 個排程任務，準備發送...")
            for task in tasks:
                push_line_message_to_users(task.message, [task.sender_id])
                if not task.repeat_daily:
                    delete_notification(task.id)
    except Exception as e:
        logger.error(f"執行排程任務發生錯誤: {e}")

def start_scheduler():
    """啟動 APScheduler"""
    # 每分鐘的 0 秒觸發
    scheduler.add_job(
        check_and_send_notifications,
        'cron',
        minute='*',
        second='0'
    )
    scheduler.start()
    logger.info("✅ APScheduler 背景排程器已啟動")
