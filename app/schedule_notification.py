#app/schedule_notification.py
from datetime import datetime, timedelta
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from app.repositories.notification_repository import (
    NotificationRecord,
    delete_notification,
    get_due_notifications,
    reschedule_notification,
)
from app.repositories.system_state_repository import try_acquire_job_lock
from app.utils.line_utils import PushResult, push_line_message_to_users
from app.utils.logger import setup_logger
from app.utils.time_utils import ONE_DAY, TAIPEI, advance_daily, format_run_at, now_taipei

logger = setup_logger("scheduler")
scheduler = AsyncIOScheduler(timezone=TAIPEI)

# 延遲超過這個時間就在訊息中註明
LATE_NOTICE_THRESHOLD = timedelta(minutes=5)
# 暫時性失敗（5xx、逾時）時，在這段時間內每分鐘重試；超過就放棄這一次
RETRY_WINDOW = timedelta(minutes=10)


def _latest_due_time(task: NotificationRecord, now: datetime) -> datetime:
    """這次應該送出的時間；每日提醒錯過多天時，以最近一次為準。"""
    if task.repeat_daily:
        return advance_daily(task.next_run_at, now) - ONE_DAY
    return task.next_run_at


def build_reminder_text(task: NotificationRecord, now: datetime) -> str:
    text = f"⏰ 提醒你：{task.message}"
    due_at = _latest_due_time(task, now)
    if now - due_at >= LATE_NOTICE_THRESHOLD:
        text += f"\n（原定 {format_run_at(due_at, False, now)}，延遲送達）"
    return text


def check_and_send_notifications():
    """每分鐘執行：送出所有已到時間的提醒。

    使用一般函式而非 async，APScheduler 會放到執行緒池執行，
    資料庫與 LINE 推送的同步呼叫才不會卡住 event loop。
    """
    try:
        if not try_acquire_job_lock("notifications", ttl_seconds=55):
            return

        now = now_taipei()
        tasks = get_due_notifications(now)
        if not tasks:
            return

        logger.info(f"發現 {len(tasks)} 個到期提醒，準備發送...")
        for task in tasks:
            due_at = _latest_due_time(task, now)
            # 同一次提醒重試時用同一個 retry key，就算上次其實已送達，LINE 也不會重複發送
            result = push_line_message_to_users(
                build_reminder_text(task, now),
                [task.sender_id],
                retry_key_base=f"reminder:{task.id}:{due_at.isoformat()}",
            )
            if result is PushResult.RETRY and now - due_at < RETRY_WINDOW:
                logger.warning(f"提醒 {task.id} 推送暫時失敗，下一分鐘重試")
                continue
            if result is PushResult.RETRY:
                logger.error(f"提醒 {task.id} 推送持續失敗，放棄本次發送")
            elif result is PushResult.FAILED:
                logger.error(f"提醒 {task.id} 無法送達（可能已被封鎖），不再重試這一次")

            if task.repeat_daily:
                reschedule_notification(task.id, advance_daily(task.next_run_at, now))
            else:
                delete_notification(task.id)
    except Exception as e:
        logger.error(f"執行排程任務發生錯誤: {e}", exc_info=True)

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
