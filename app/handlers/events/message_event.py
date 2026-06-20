from linebot.models import TextSendMessage, QuickReply, QuickReplyButton, MessageAction
from app.config import config
from app.utils.logger import setup_logger
from app.utils.decorators import handle_exceptions, rate_limit
from app.utils.line_utils import (
    get_sender_id, get_chat_id, safe_reply, show_loading_animation, 
    get_memory_id, get_or_fetch_user_name, line_bot_api, safe_reply_message,
    format_user_message_for_memory, is_multi_user_chat
)
from app.repositories.user_repository import get_user_state
from app.repositories.notification_repository import get_user_notifications
from app.realtime_search import needs_realtime_info
from app.handlers.command_handler import command_processor
from app.services.conversation_service import get_conversation_reply
from app.services.realtime_service import get_realtime_reply
from app.services.restaurant_service import get_restaurant_recommendation
from app.views.line_menus import build_quick_intro_message, build_quick_help_message

logger = setup_logger("message_event")

@handle_exceptions("⚠️ 提醒列表處理失敗")
def handle_reminder_list(event, sender_id: str):
    notifications = get_user_notifications(sender_id)
    state = get_user_state(sender_id)
    
    if not notifications:
        safe_reply(event, "📭 你目前沒有任何提醒喔！")
        return
    
    lines = ["📋你的提醒列表："]
    for b in notifications:
        lines.append(f"• 編號: {b.id}｜{'每天' if b.repeat_daily else '一次'}｜{b.time.strftime('%H:%M')}｜{b.message}")

    if len(notifications) > 8:
        lines.append("\n...還有更多提醒，請使用「我的提醒」來查看。\n如果要刪除，請輸入：\n取消提醒 <編號>")

    buttons = [QuickReplyButton(action=MessageAction(label="刪除全部提醒", text="刪除全部提醒"))]
    for b in notifications[:8]:
        label = f"取消提醒 {b.id}"
        text = f"@G-bot 取消提醒 {b.id}" if "mention" in state else f"取消提醒 {b.id}"
        buttons.append(QuickReplyButton(action=MessageAction(label=label, text=text)))
    
    buttons.append(QuickReplyButton(action=MessageAction(label="取消", text="#選單")))
    
    msg = TextSendMessage(
        text="\n".join(lines),
        quick_reply=QuickReply(items=buttons)
    )
    
    try:
        line_bot_api.reply_message(event.reply_token, msg)
    except Exception as e:
        logger.error(f"提醒列表回覆失敗: {e}")
        safe_reply(event, "\n".join(lines))

@handle_exceptions("⚠️ 餐廳搜尋失敗")
def handle_restaurant_search(event, sender_id: str, user_input: str):
    chat_id = get_chat_id(event)
    show_loading_animation(chat_id)
    try:
        result = get_restaurant_recommendation(sender_id, user_input)
        safe_reply(event, result)
    except Exception as e:
        logger.error(f"餐廳搜尋失敗: {e}")
        safe_reply(event, "⚠️ 餐廳推薦失敗，請稍後再試")

@handle_exceptions("⚠️ 即時查詢失敗")
def handle_realtime_query(event, memory_id: str, user_input: str):
    chat_id = get_chat_id(event)
    show_loading_animation(chat_id)
    try:
        sender_id = get_sender_id(event)
        memory_user_input = format_user_message_for_memory(event, sender_id, user_input)
        reply = get_realtime_reply(
            memory_id=memory_id,
            user_input=user_input,
            memory_user_input=memory_user_input,
        )
        msg = TextSendMessage(
            text=reply,
            quick_reply=QuickReply(items=[
                QuickReplyButton(action=MessageAction(label="查更詳細", text="查更詳細"))
            ])
        )
        safe_reply_message(event, msg)
    except Exception as e:
        logger.error(f"即時查詢失敗: {e}")
        safe_reply(event, "⚠️ 即時查詢失敗，請稍後再試")

@handle_exceptions("⚠️ 對話處理失敗")
def handle_gemini_conversation(event, sender_id: str, memory_id: str, user_input: str):
    chat_id = get_chat_id(event)
    show_loading_animation(chat_id)
    
    user_name = get_or_fetch_user_name(event, sender_id)
    memory_user_input = format_user_message_for_memory(event, sender_id, user_input)
    reply = get_conversation_reply(
        memory_id=memory_id,
        sender_id=sender_id,
        user_input=user_input,
        memory_user_input=memory_user_input,
        user_name=user_name,
        is_multi_user_chat=is_multi_user_chat(event),
    )
    safe_reply(event, reply)

@handle_exceptions("⚠️ 特殊回覆處理失敗")
def handle_special_reply(event, special_type: str, sender_id: str):
    if special_type == "#選單":
        msg = build_quick_intro_message(event, sender_id)
        line_bot_api.reply_message(event.reply_token, msg)
    elif special_type == "#幫助":
        msg = build_quick_help_message(event)
        line_bot_api.reply_message(event.reply_token, msg)
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
                safe_reply(event, command_result.message)
        else:
            safe_reply(event, command_result.message)
        return

    state = get_user_state(chat_id)
    if "silent" in state:
        if "mention" in state:
            safe_reply(event, "⚠️ 我現在是靜音狀態，請先取消靜音我才會回覆你ㄛ。")
        return
    
    if "mention" in state:
        if not any(kw in user_input.lower() for kw in config.MENTION_KEYWORDS):
            return
        else:
            lowered_input = user_input.lower()
            for keyword in config.MENTION_KEYWORDS:
                lowered_input = lowered_input.replace(keyword, "")
            user_input = lowered_input.strip()
        
    if "吃什麼" in user_input:
        handle_restaurant_search(event, sender_id, user_input)
        return

    if user_input == "查更詳細" or needs_realtime_info(user_input):
        handle_realtime_query(event, memory_id, user_input)
        return

    handle_gemini_conversation(event, sender_id, memory_id, user_input)
