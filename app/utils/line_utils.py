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
def push_line_message_to_users(message: str, user_ids: list[str], image_url: str = None):
    from linebot.models import ImageSendMessage
    
    messages = [TextSendMessage(text=message)]
    if image_url:
        messages.append(ImageSendMessage(original_content_url=image_url, preview_image_url=image_url))

    for uid in user_ids:
        try:
            line_bot_api.push_message(uid, messages)
            logger.info(f"成功推送訊息給用戶: {uid}")
        except Exception as e:
            logger.error(f"推送失敗給用戶 {uid}: {e}")

def get_sender_id(event) -> str:
    source = event.source
    if hasattr(source, 'user_id') and source.user_id:
        return source.user_id
    return "unknown"

def get_chat_id(event) -> str:
    source = event.source
    if source.type == 'user': return source.user_id
    elif source.type == 'group': return source.group_id
    elif source.type == 'room': return source.room_id
    return "unknown"

def get_memory_id(event) -> str:
    sender_id = get_sender_id(event)
    chat_id = get_chat_id(event)
    if event.source.type in ["group", "room"]:
        return chat_id
    return sender_id if sender_id == chat_id else f"{chat_id}:{sender_id}"

def is_multi_user_chat(event) -> bool:
    return event.source.type in ["group", "room"]

def format_user_message_for_memory(event, sender_id: str, user_input: str) -> str:
    if not is_multi_user_chat(event):
        return user_input

    user_name = get_or_fetch_user_name(event, sender_id)
    return f"{user_name}：{user_input}"

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
    safe_reply_message(event, TextSendMessage(text=message))

def safe_reply_message(event, send_message):
    try:
        line_bot_api.reply_message(event.reply_token, send_message)
        logger.debug(f"成功回覆訊息給 {get_sender_id(event)}")
    except Exception as e:
        logger.warning(f"reply_message 失敗，改用推播: {e}")
        try:
            line_bot_api.push_message(get_chat_id(event), send_message)
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
    loading_seconds = max(5, min(config.LINE_LOADING_SECONDS, 60))
    def send_loading_request():
        url = "https://api.line.me/v2/bot/chat/loading/start"
        payload = {"chatId": chat_id, "loadingSeconds": loading_seconds}
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
    except Exception as e:
        logger.warning(f"無法取得用戶資料: {e}")
        return f"未知使用者({sender_id[-6:]})" if sender_id and sender_id != "unknown" else "未知使用者"
