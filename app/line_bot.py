from linebot import WebhookHandler
from linebot.models import MessageEvent, TextMessage, LocationMessage
import threading
from app.handlers.events.location_event import handle_location
from app.handlers.events.message_event import handle_message
from app.utils.logger import setup_logger

logger = setup_logger("line_bot")

def _run_in_background(action_name: str, handler_func, event):
    def run():
        try:
            handler_func(event)
        except Exception as e:
            logger.error(f"{action_name}背景處理失敗: {e}", exc_info=True)

    thread = threading.Thread(target=run, daemon=True)
    thread.start()

def handle_events(handler: WebhookHandler):
    """註冊 LINE Bot 的事件處理器"""
    
    @handler.add(MessageEvent, message=LocationMessage)
    def wrapper_handle_location(event):
        try:
            logger.info("收到位置訊息事件")
            _run_in_background("位置訊息", handle_location, event)
        except Exception as e:
            logger.error(f"路由位置訊息時發生錯誤: {e}", exc_info=True)

    @handler.add(MessageEvent, message=TextMessage)
    def wrapper_handle_message(event):
        try:
            logger.info("收到文字訊息事件")
            _run_in_background("文字訊息", handle_message, event)
        except Exception as e:
            logger.error(f"路由文字訊息時發生錯誤: {e}", exc_info=True)
