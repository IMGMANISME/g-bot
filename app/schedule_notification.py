#app/schedule_notification.py
from datetime import datetime, timedelta
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from app.repositories.notification_repository import (
    NotificationRecord,
    backfill_missing_next_run_at,
    delete_notification,
    get_due_notifications,
    reschedule_notification,
)
from app.repositories.system_state_repository import try_acquire_job_lock
from app.utils.line_utils import push_line_message_to_users
from app.utils.logger import setup_logger
from app.utils.time_utils import ONE_DAY, TAIPEI, advance_daily, format_run_at, now_taipei

logger = setup_logger("scheduler")
scheduler = AsyncIOScheduler(timezone=TAIPEI)

# 延遲超過這個時間就在訊息中註明
LATE_NOTICE_THRESHOLD = timedelta(minutes=5)
# 推送失敗時，在這段時間內每分鐘重試；超過就放棄這一次
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
            sent = push_line_message_to_users(build_reminder_text(task, now), [task.sender_id]) is True
            if not sent and now - _latest_due_time(task, now) < RETRY_WINDOW:
                logger.warning(f"提醒 {task.id} 推送失敗，下一分鐘重試")
                continue
            if not sent:
                logger.error(f"提醒 {task.id} 推送持續失敗，放棄本次發送")

            if task.repeat_daily:
                reschedule_notification(task.id, advance_daily(task.next_run_at, now))
            else:
                delete_notification(task.id)
    except Exception as e:
        logger.error(f"執行排程任務發生錯誤: {e}", exc_info=True)

def start_scheduler():
    """啟動 APScheduler"""
    backfilled = backfill_missing_next_run_at(now_taipei())
    if backfilled:
        logger.info(f"已為 {backfilled} 筆舊提醒補上下次送出時間")

    # 每分鐘的 0 秒觸發
    scheduler.add_job(
        check_and_send_notifications,
        'cron',
        minute='*',
        second='0'
    )
    scheduler.start()
    logger.info("✅ APScheduler 背景排程器已啟動")
