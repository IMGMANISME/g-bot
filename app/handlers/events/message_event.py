from app.config import config
from app.utils.logger import setup_logger
from app.utils.decorators import handle_exceptions, rate_limit
from app.utils.time_utils import format_run_at, now_taipei
from app.utils.line_utils import (
    get_sender_id, get_chat_id, safe_reply, safe_reply_message, show_loading_animation,
    get_memory_id, get_or_fetch_user_name,
    format_user_message_for_memory, is_multi_user_chat
)
from app.repositories.user_repository import get_user_state
from app.repositories.notification_repository import get_user_notifications
from app.handlers.command_handler import command_processor
from app.services.assistant_service import get_assistant_reply
from app.tools.base import QuickReplyItem
from app.views.line_menus import build_quick_intro_message, build_quick_help_message, build_reply_message, mention_prefix

logger = setup_logger("message_event")

@handle_exceptions("⚠️ 提醒列表處理失敗")
def handle_reminder_list(event, sender_id: str):
    notifications = get_user_notifications(sender_id)
    state = get_user_state(sender_id)
    
    if not notifications:
        safe_reply_message(event, build_reply_message(
            "📭 你目前沒有任何提醒。想設的話直接跟我說，例如「明天早上八點提醒我開會」。",
            [QuickReplyItem("10 分鐘後提醒我", f"{mention_prefix(state)}10分鐘後提醒我喝水")],
        ))
        return
    
    now = now_taipei()
    lines = ["📋你的提醒列表："]
    for b in notifications:
        when = format_run_at(b.next_run_at, b.repeat_daily, now)
        lines.append(f"• 編號 {b.id}｜{when}｜{b.message}")

    if len(notifications) > 8:
        lines.append("\n...還有更多提醒，請使用「我的提醒」來查看。\n如果要刪除，請輸入：\n取消提醒 <編號>")

    prefix = mention_prefix(state)
    buttons = [QuickReplyItem("刪除全部提醒", f"{prefix}刪除全部提醒")]
    buttons += [QuickReplyItem(f"取消提醒 {b.id}", f"{prefix}取消提醒 {b.id}") for b in notifications[:8]]
    buttons.append(QuickReplyItem("取消", f"{prefix}#選單"))
    safe_reply_message(event, build_reply_message("\n".join(lines), buttons))

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
    safe_reply_message(event, build_reply_message(reply.text, reply.quick_replies))

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
        
    handle_assistant_message(event, sender_id, chat_id, memory_id, user_input, mention_prefix(state))
