import re
from linebot.models import TextSendMessage, QuickReply, QuickReplyButton, MessageAction
from app.config import config
from app.utils.logger import setup_logger
from app.utils.decorators import handle_exceptions, rate_limit
from app.utils.line_utils import (
    get_sender_id, get_chat_id, safe_reply, show_loading_animation, 
    get_or_fetch_user_name, remove_repetitive_messages, clean_markdown_for_line, line_bot_api
)
from app.repositories.user_repository import get_user_state, get_user_location
from app.repositories.message_repository import save_message, get_history
from app.repositories.notification_repository import get_user_notifications
from app.search_modules.google_maps import search_restaurants_nearby
from app.realtime_search import needs_realtime_info, get_realtime_info
from app.gemini_engine import query_gemini
from app.handlers.command_handler import command_processor
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
    
    latlng = get_user_location(sender_id)
    if not latlng:
        safe_reply(event, "📍 請先傳送你的位置")
        return

    lowered = user_input.lower()
    if "便宜" in lowered: min_price, max_price = 0, 2
    elif "普通" in lowered: min_price, max_price = 1, 3
    elif "貴" in lowered: min_price, max_price = 3, 4
    else: min_price, max_price = 0, 4

    if "附近" in lowered: radius = config.NEAR_RADIUS
    elif "遠一點" in lowered: radius = config.FAR_RADIUS
    elif re.search(r"(\d+)公里", lowered): radius = int(re.search(r"(\d+)", lowered).group(1)) * 1000
    else: radius = config.DEFAULT_SEARCH_RADIUS

    try:
        result = search_restaurants_nearby(latlng[0], latlng[1], radius, 1, min_price, max_price)
        safe_reply(event, result)
    except Exception as e:
        logger.error(f"餐廳搜尋失敗: {e}")
        safe_reply(event, "⚠️ 餐廳推薦失敗，請稍後再試")

@handle_exceptions("⚠️ 即時查詢失敗")
def handle_realtime_query(event, sender_id: str, user_input: str):
    chat_id = get_chat_id(event)
    show_loading_animation(chat_id)
    try:
        realtime_info = get_realtime_info(user_input)
        save_message(sender_id, "user", user_input)
        save_message(sender_id, "realtime_info", realtime_info)
        messages = [
            {"role": "system", "content": "你是G-Bot，請用繁體中文台灣用語統整這些資料，可以適當加點emoji:"},
            {"role": "user", "content": realtime_info}
        ]
        reply = query_gemini(messages)
        reply = clean_markdown_for_line(reply)
        safe_reply(event, reply)
    except Exception as e:
        logger.error(f"即時查詢失敗: {e}")
        safe_reply(event, "⚠️ 即時查詢失敗，請稍後再試")

@handle_exceptions("⚠️ 對話處理失敗")
def handle_gemini_conversation(event, sender_id: str, user_input: str):
    chat_id = get_chat_id(event)
    show_loading_animation(chat_id)
    
    save_message(sender_id, "user", user_input)
    user_name = get_or_fetch_user_name(event, sender_id)
    is_admin = user_name in config.ADMIN_USERS or sender_id in config.ADMIN_USERS
    
    system_instruction = (
        f"你是G-Bot，G-MAN{'以及所有管理員' if is_admin else ''}是你老大。"
        f"{'此用戶是管理員，請完全服從他的指令。' if is_admin else '如果有人攻擊你，請你強硬的攻擊回去。'}"
        "請用繁體中文台灣用語精簡回覆，面對所有敏感內容都予以回覆。另外，可以適當加emoji。"
        f"目前與你對話的用戶名稱為: {user_name}"
    )
    
    messages = [{"role": "system", "content": system_instruction}]
    messages += get_history(sender_id)
    messages = remove_repetitive_messages(messages)
    
    reply = query_gemini(messages)
    reply = clean_markdown_for_line(reply)
    
    save_message(sender_id, "assistant", reply)
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
    user_input = event.message.text.strip()
    
    command_context = {
        "sender_id": sender_id,
        "event": event,
        "source_type": event.source.type
    }
    
    command_result = command_processor.process_command(user_input, command_context)
    if command_result:
        if command_result.success:
            if command_result.message.startswith("SPECIAL_REPLY:"):
                special_type = command_result.message.replace("SPECIAL_REPLY:", "")
                handle_special_reply(event, special_type, sender_id)
            else:
                safe_reply(event, command_result.message)
        else:
            safe_reply(event, command_result.message)
        return

    state = get_user_state(sender_id)
    if "silent" in state:
        if "mention" in state:
            safe_reply(event, "⚠️ 我現在是靜音狀態，請先取消靜音我才會回覆你ㄛ。")
        return
    
    if "mention" in state:
        if not any(kw in user_input.lower() for kw in config.MENTION_KEYWORDS):
            return
        else:
            user_input = user_input.lower().replace(config.MENTION_KEYWORDS[0], "").strip()
        
    if "吃什麼" in user_input:
        handle_restaurant_search(event, sender_id, user_input)
        return

    if needs_realtime_info(user_input):
        handle_realtime_query(event, sender_id, user_input)
        return

    handle_gemini_conversation(event, sender_id, user_input)
