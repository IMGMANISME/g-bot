import re

from app.config import config
from app.utils.cache import global_cache
from app.utils.logger import setup_logger
from app.utils.decorators import handle_exceptions, rate_limit
from app.utils.time_utils import now_taipei
from app.utils.line_utils import (
    get_sender_id, get_chat_id, safe_reply, safe_reply_message, show_loading_animation,
    get_memory_id, get_or_fetch_user_name,
    format_user_message_for_memory, is_multi_user_chat
)
from app.repositories.user_repository import get_user_state
from app.repositories.notification_repository import get_user_notifications
from app.handlers.command_handler import command_processor
from app.services.assistant_service import get_assistant_reply
from app.tools.base import QuickReplyItem, postback_data
from app.tools.guide import GUIDE_ACTION
from app.tools.reminders import build_reminder_list, due_nudges, mark_nudged, reminder_buttons
from app.tools.water import take_window_answer
from app.views.line_menus import build_quick_intro_message, build_quick_help_message, build_reply_message, mention_prefix

logger = setup_logger("message_event")

@handle_exceptions("⚠️ 提醒列表處理失敗")
def handle_reminder_list(event, sender_id: str):
    result = build_reminder_list(get_user_notifications(sender_id), now_taipei(), mention_prefix(get_user_state(sender_id)))
    safe_reply_message(event, build_reply_message(result.fallback_text, result.quick_replies))

@handle_exceptions("⚠️ 對話處理失敗")
def handle_assistant_message(event, sender_id: str, chat_id: str, memory_id: str, user_input: str, prefix: str):
    show_loading_animation(chat_id)

    user_name = get_or_fetch_user_name(event, sender_id)
    reply = get_assistant_reply(
        memory_id=memory_id,
        chat_id=chat_id,
        sender_id=sender_id,
        user_input=user_input,
        memory_user_input=format_user_message_for_memory(event, sender_id, user_input),
        user_name=user_name,
        is_multi_user_chat=is_multi_user_chat(event),
        mention_prefix=prefix,
    )

    nudges = _due_nudges(chat_id)
    nudge_messages = [
        build_reply_message(f"⏰ 順便提醒你：{record.message}", reminder_buttons(record))
        for record in nudges
    ]
    if safe_reply_message(event, build_reply_message(reply.text, reply.quick_replies), *nudge_messages):
        now = now_taipei()
        for record in nudges:
            mark_nudged(record, now)


# 標記模式下有人提到我、但沒有標記時，主動回一句（同一個聊天室一段時間內只回一次）
CALLED_PATTERN = re.compile(r"g[\s\-_]?bot|機器人", re.IGNORECASE)
CALLED_HINT_COOLDOWN_SECONDS = 10 * 60


def answer_if_called(event, chat_id: str):
    if not CALLED_PATTERN.search(event.message.text or ""):
        return
    key = f"called_hint:{chat_id}"
    if global_cache.get(key):
        return
    global_cache.set(key, True, ttl=CALLED_HINT_COOLDOWN_SECONDS)
    safe_reply_message(event, build_reply_message(
        "有人叫我嗎？👀\n要找我幫忙的話，在訊息前面加上「@G-bot」，例如「@G-bot 台北天氣」。",
        [
            QuickReplyItem("我會做什麼", data=postback_data(GUIDE_ACTION, "overview")),
            QuickReplyItem("@G-bot 台北天氣", "@G-bot 台北天氣"),
        ],
    ))


# 一次回覆最多 5 則訊息，主要回覆佔 1 則
MAX_NUDGES_PER_REPLY = 4


def _due_nudges(chat_id: str) -> list:
    """一對一聊天時，該順便提醒的週期提醒（回覆不花推播額度）；查詢失敗不影響正常回覆"""
    try:
        return due_nudges(chat_id, now_taipei())[:MAX_NUDGES_PER_REPLY]
    except Exception as e:
        logger.warning(f"查詢順便提醒失敗: {e}")
        return []

@handle_exceptions("⚠️ 特殊回覆處理失敗")
def handle_special_reply(event, special_type: str, sender_id: str):
    if special_type == "#選單":
        safe_reply_message(event, build_quick_intro_message(event, sender_id))
    elif special_type == "#幫助":
        safe_reply_message(event, build_quick_help_message(event))
    elif special_type == "我的提醒":
        handle_reminder_list(event, sender_id)

@rate_limit(calls_per_minute=30)
def handle_message(event):
    sender_id = get_sender_id(event)
    chat_id = get_chat_id(event)
    memory_id = get_memory_id(event)
    user_input = event.message.text.strip()
    
    command_context = {
        "sender_id": sender_id,
        "chat_id": chat_id,
        "state_id": chat_id,
        "memory_id": memory_id,
        "event": event,
        "source_type": event.source.type,
        "mention_keywords": config.MENTION_KEYWORDS
    }
    
    command_result = command_processor.process_command(user_input, command_context)
    if command_result:
        if command_result.success:
            if command_result.message.startswith("SPECIAL_REPLY:"):
                special_type = command_result.message.replace("SPECIAL_REPLY:", "")
                handle_special_reply(event, special_type, chat_id)
            else:
                safe_reply_message(event, build_reply_message(command_result.message, command_result.quick_replies))
        else:
            safe_reply_message(event, build_reply_message(command_result.message, command_result.quick_replies))
        return

    state = get_user_state(chat_id)
    mentioned = any(kw in user_input.lower() for kw in config.MENTION_KEYWORDS)
    if "silent" in state:
        # 只在被標記時提醒「我在靜音」，不然群組裡每則訊息都會被回
        if "mention" in state and mentioned:
            safe_reply(event, "⚠️ 我現在是靜音狀態，請先取消靜音我才會回覆你ㄛ。")
        return
    
    if "mention" in state:
        if not mentioned:
            answer_if_called(event, chat_id)
            return
        else:
            lowered_input = user_input.lower()
            for keyword in config.MENTION_KEYWORDS:
                lowered_input = lowered_input.replace(keyword, "")
            user_input = lowered_input.strip()
        
    # 剛問過喝水提醒的時段，這句是在回答時段：改寫成完整的設定句交給模型
    user_input = take_window_answer(chat_id, user_input) or user_input
    handle_assistant_message(event, sender_id, chat_id, memory_id, user_input, mention_prefix(state))
