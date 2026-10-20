# app/utils/line_utils.py
"""LINE Messaging API（SDK v3）的共用工具：所有呼叫 LINE API 的地方都集中在這裡。"""
import re
import threading
import uuid
from enum import Enum

from linebot.v3.messaging import (
    ApiClient,
    ApiException,
    Configuration,
    ImageMessage,
    MessagingApi,
    PushMessageRequest,
    ReplyMessageRequest,
    ShowLoadingAnimationRequest,
    TextMessage,
)

from app.config import config
from app.utils.logger import setup_logger

logger = setup_logger("line_utils")

messaging_api = MessagingApi(ApiClient(Configuration(access_token=config.LINE_CHANNEL_ACCESS_TOKEN)))

# 推播重試用的 Retry Key 命名空間：同一則推播產生相同的 key，LINE 會擋掉重複發送
_RETRY_KEY_NAMESPACE = uuid.UUID("6f1c2f3e-5d0a-4c8e-9a51-3b7e2d1c0f42")


class PushResult(Enum):
    SENT = "sent"  # 已送出（包含先前已被接受的重送）
    RETRY = "retry"  # 暫時性失敗（5xx、逾時、連線錯誤），可以用同一個 retry key 重試
    FAILED = "failed"  # 重試也不會成功（4xx，例如使用者封鎖了帳號）


def make_retry_key(*parts) -> str:
    return str(uuid.uuid5(_RETRY_KEY_NAMESPACE, ":".join(str(p) for p in parts)))


def reply_message(reply_token: str, *messages) -> None:
    messaging_api.reply_message(ReplyMessageRequest(reply_token=reply_token, messages=list(messages)))


def push_message(to: str, *messages, retry_key: str | None = None) -> PushResult:
    """推播訊息；依 LINE 文件，只有 5xx 與逾時值得重試，409 代表同一個 retry key 已經送過。"""
    try:
        messaging_api.push_message(PushMessageRequest(to=to, messages=list(messages)), x_line_retry_key=retry_key)
        return PushResult.SENT
    except ApiException as e:
        if e.status == 409:
            logger.info(f"推播先前已送出（retry key 重複）- to: {to}")
            return PushResult.SENT
        if e.status and e.status >= 500:
            logger.warning(f"推播暫時失敗 {e.status} - to: {to}")
            return PushResult.RETRY
        logger.error(f"推播失敗 {e.status} - to: {to}: {e.body}")
        return PushResult.FAILED
    except Exception as e:
        logger.warning(f"推播連線失敗 - to: {to}: {e}")
        return PushResult.RETRY


def push_line_message_to_users(
    message: str,
    user_ids: list[str],
    image_url: str | None = None,
    retry_key_base: str | None = None,
) -> PushResult:
    """推播文字（可附圖片）給多個聊天室；回傳最差的結果。

    retry_key_base 會和每個收件者組成各自的 retry key，同一則推播重試時不會重複發送。
    """
    messages = [TextMessage(text=message)]
    if image_url:
        messages.append(ImageMessage(original_content_url=image_url, preview_image_url=image_url))

    results = []
    for uid in user_ids:
        retry_key = make_retry_key(retry_key_base, uid, message) if retry_key_base else None
        result = push_message(uid, *messages, retry_key=retry_key)
        if result is PushResult.SENT:
            logger.info(f"成功推送訊息給: {uid}")
        results.append(result)

    for worst in (PushResult.RETRY, PushResult.FAILED):
        if worst in results:
            return worst
    return PushResult.SENT


def get_sender_id(event) -> str:
    return getattr(event.source, "user_id", None) or "unknown"


def get_chat_id(event) -> str:
    source = event.source
    if source.type == "user":
        return source.user_id
    if source.type == "group":
        return source.group_id
    if source.type == "room":
        return source.room_id
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


def _quote_in_group(event, message):
    """群組裡回覆時引用對方的訊息，大家才知道我在回誰；一對一聊天不需要。"""
    quote_token = getattr(getattr(event, "message", None), "quote_token", None)
    if is_multi_user_chat(event) and quote_token and isinstance(message, TextMessage) and not message.quote_token:
        message.quote_token = quote_token
    return message


def safe_reply(event, message: str):
    return safe_reply_message(event, TextMessage(text=message))


def safe_reply_message(event, send_message) -> bool:
    send_message = _quote_in_group(event, send_message)
    try:
        reply_message(event.reply_token, send_message)
        logger.debug(f"成功回覆訊息給 {get_sender_id(event)}")
        return True
    except Exception as e:
        logger.warning(f"reply_message 失敗，改用推播: {e}")
        result = push_message(get_chat_id(event), send_message)
        if result is PushResult.SENT:
            logger.info(f"reply fallback push_message 成功 - chat_id: {get_chat_id(event)}")
            return True
        logger.error(f"push_message 也失敗：{result.value}")
        return False


def show_loading_animation(chat_id: str):
    """顯示「輸入中」動畫；LINE 只支援一對一聊天（user ID 以 U 開頭），群組直接略過。"""
    if not config.ENABLE_LOADING_ANIMATION or not chat_id.startswith("U"):
        return
    loading_seconds = max(5, min(config.LINE_LOADING_SECONDS, 60))

    def send():
        try:
            messaging_api.show_loading_animation(
                ShowLoadingAnimationRequest(chat_id=chat_id, loading_seconds=loading_seconds)
            )
            logger.info(f"Loading 動畫顯示成功 - chat_id: {chat_id}")
        except Exception as e:
            logger.warning(f"Loading 動畫顯示失敗: {e}")

    threading.Thread(target=send, daemon=True).start()


def get_or_fetch_user_name(event, sender_id: str) -> str:
    from app.repositories.user_repository import get_cached_user_profile, upsert_user_profile
    cached = get_cached_user_profile(sender_id)
    if cached and cached["display_name"]:
        return cached["display_name"]
    try:
        if event.source.type == 'group':
            profile = messaging_api.get_group_member_profile(event.source.group_id, sender_id)
        elif event.source.type == 'room':
            profile = messaging_api.get_room_member_profile(event.source.room_id, sender_id)
        else:
            profile = messaging_api.get_profile(sender_id)
        display_name = profile.display_name
        upsert_user_profile(sender_id, display_name, profile.picture_url)
        return display_name
    except Exception as e:
        logger.warning(f"無法取得用戶資料: {e}")
        return f"未知使用者({sender_id[-6:]})" if sender_id and sender_id != "unknown" else "未知使用者"


def get_message_quota() -> dict:
    """本月推播額度與已使用量（回覆訊息不計入額度）。"""
    try:
        quota = messaging_api.get_message_quota()
        consumption = messaging_api.get_message_quota_consumption()
        return {
            "type": quota.type,  # limited：有上限；none：無上限
            "limit": quota.value,
            "used": consumption.total_usage,
        }
    except Exception as e:
        logger.warning(f"無法取得訊息額度: {e}")
        return {"error": str(e)}


def get_chat_member_count(chat_id: str) -> int | None:
    """聊天室人數：一對一為 1，群組／聊天室向 LINE 查詢；查不到回傳 None。"""
    try:
        if chat_id.startswith("C"):
            return messaging_api.get_group_member_count(chat_id).count
        if chat_id.startswith("R"):
            return messaging_api.get_room_member_count(chat_id).count
        return 1
    except Exception as e:
        logger.warning(f"無法取得聊天室人數: {e}")
        return None
