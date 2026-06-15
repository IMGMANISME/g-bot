from linebot import WebhookHandler
from linebot.models import MessageEvent, TextMessage, LocationMessage
import time
from concurrent.futures import ThreadPoolExecutor
from app.handlers.events.location_event import handle_location
from app.handlers.events.message_event import handle_message
from app.utils.logger import setup_logger
from app.utils.performance import performance_monitor

logger = setup_logger("line_bot")
background_executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="line-event")

def _run_in_background(action_name: str, handler_func, event):
    def run():
        start_time = time.time()
        metric_prefix = f"line_background_{action_name}"
        performance_monitor.increment_counter(f"{metric_prefix}_started")
        try:
            handler_func(event)
            performance_monitor.increment_counter(f"{metric_prefix}_succeeded")
        except Exception as e:
            performance_monitor.increment_counter(f"{metric_prefix}_failed")
            logger.error(f"{action_name}背景處理失敗: {e}", exc_info=True)
        finally:
            duration_ms = (time.time() - start_time) * 1000
            performance_monitor.record_metric(f"{metric_prefix}_duration_ms", duration_ms)

    try:
        background_executor.submit(run)
    except Exception as e:
        performance_monitor.increment_counter(f"line_background_{action_name}_submit_failed")
        logger.error(f"{action_name}背景任務送出失敗: {e}", exc_info=True)


def shutdown_background_executor():
    background_executor.shutdown(wait=False, cancel_futures=True)

def handle_events(handler: WebhookHandler):
    """註冊 LINE Bot 的事件處理器"""
    
    @handler.add(MessageEvent, message=LocationMessage)
    def wrapper_handle_location(event):
        try:
            logger.info("收到位置訊息事件")
            _run_in_background("location_message", handle_location, event)
        except Exception as e:
            logger.error(f"路由位置訊息時發生錯誤: {e}", exc_info=True)

    @handler.add(MessageEvent, message=TextMessage)
    def wrapper_handle_message(event):
        try:
            logger.info("收到文字訊息事件")
            _run_in_background("text_message", handle_message, event)
        except Exception as e:
            logger.error(f"路由文字訊息時發生錯誤: {e}", exc_info=True)
