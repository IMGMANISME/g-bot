from linebot import LineBotApi
from linebot.models import TextSendMessage
from app.config import config
from app.utils.logger import setup_logger
from app.utils.decorators import handle_exceptions
import re
import threading
import requests

logger = setup_logger("line_utils")
line_bot_api = LineBotApi(config.LINE_CHANNEL_ACCESS_TOKEN)

@handle_exceptions("⚠️ 訊息推送失敗")
def push_line_message_to_users(message: str, user_ids: list[str]):
    for uid in user_ids:
        try:
            line_bot_api.push_message(uid, TextSendMessage(text=message))
            logger.info(f"成功推送訊息給用戶: {uid}")
        except Exception as e:
            logger.error(f"推送失敗給用戶 {uid}: {e}")

def get_sender_id(event) -> str:
    source = event.source
    if source.type == 'user': return source.user_id
    elif source.type == 'group': return source.group_id
    elif source.type == 'room': return source.room_id
    return "unknown"

def get_chat_id(event) -> str:
    if hasattr(event.source, 'user_id'): return event.source.user_id
    elif hasattr(event.source, 'group_id'): return event.source.group_id
    elif hasattr(event.source, 'room_id'): return event.source.room_id
    return get_sender_id(event)

def clean_markdown_for_line(text: str) -> str:
    text = re.sub(r'^\* ', '• ', text, flags=re.MULTILINE)
    text = re.sub(r'\*\*(.*?)\*\*', r'\1', text)
    text = re.sub(r'\*(.*?)\*', r'\1', text)
    return text.replace("*", "").strip()

def remove_repetitive_messages(messages: list) -> list:
    cleaned = []
    prev = None
    for m in messages:
        if m["role"] == "user" and m["content"] == prev:
            continue
        cleaned.append(m)
        prev = m["content"] if m["role"] == "user" else None
    return cleaned

def safe_reply(event, message: str):
    try:
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text=message))
        logger.debug(f"成功回覆訊息給 {get_sender_id(event)}")
    except Exception as e:
        logger.warning(f"reply_message 失敗，改用推播: {e}")
        try:
            line_bot_api.push_message(get_sender_id(event), TextSendMessage(text=message))
        except Exception as push_error:
            logger.error(f"push_message 也失敗：{push_error}")

def _send_loading_request(url: str, payload: dict, action_name: str):
    try:
        headers = {
            "Authorization": f"Bearer {config.LINE_CHANNEL_ACCESS_TOKEN}",
            "Content-Type": "application/json"
        }
        res = requests.post(url, headers=headers, json=payload, timeout=5)
        if res.status_code in [200, 202]:
            logger.info(f"{action_name}成功 - chat_id: {payload.get('chatId')}")
        else:
            logger.warning(f"{action_name}失敗: {res.status_code}")
    except Exception as e:
        logger.warning(f"{action_name}執行失敗: {e}")

def show_loading_animation(chat_id: str):
    if not config.ENABLE_LOADING_ANIMATION:
        return
    def send_loading_request():
        url = "https://api.line.me/v2/bot/chat/loading/start"
        payload = {"chatId": chat_id, "loadingSeconds": 60}
        _send_loading_request(url, payload, "Loading 動畫顯示")
    thread = threading.Thread(target=send_loading_request)
    thread.daemon = True
    thread.start()

@handle_exceptions("⚠️ 非同步回覆失敗")
def safe_reply_with_loading(event, message: str):
    chat_id = get_chat_id(event)
    show_loading_animation(chat_id)
    safe_reply(event, message)

def get_or_fetch_user_name(event, sender_id: str) -> str:
    from app.repositories.user_repository import get_cached_user_profile, upsert_user_profile
    cached = get_cached_user_profile(sender_id)
    if cached and cached["display_name"]:
        return cached["display_name"]
    try:
        if event.source.type == 'group':
            profile = line_bot_api.get_group_member_profile(event.source.group_id, sender_id)
        elif event.source.type == 'room':
            profile = line_bot_api.get_room_member_profile(event.source.room_id, sender_id)
        else:
            profile = line_bot_api.get_profile(sender_id)
        display_name = profile.display_name
        upsert_user_profile(sender_id, display_name, profile.picture_url)
        return display_name
    except BaseException as e:
        logger.warning(f"無法取得用戶資料: {e}")
        return "Unknown User"
