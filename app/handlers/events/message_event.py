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


def _force_clarify_when_name_query_looks_ambiguous(user_input: str, reply: str) -> str:
    """針對「X是誰」且模型輸出分析語氣時，改為一句澄清問題。"""
    if not user_input or not reply:
        return reply

    query_match = re.match(r"^\s*([\u4e00-\u9fffA-Za-z0-9·]{1,12})\s*是誰[？?]?\s*$", user_input)
    if not query_match:
        return reply

    analysis_markers = ["看起來", "語境", "詞組", "意思是", "推測", "判斷"]
    if any(marker in reply for marker in analysis_markers):
        target = query_match.group(1).strip()
        return f"你是想問「{target}」是哪位人物嗎？請給我更完整或正確的名字，我直接回答你。"

    return reply

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

    if "便宜" in lowered:
        min_price, max_price = 0, 2
    elif "普通" in lowered:
        min_price, max_price = 1, 3
    elif "貴" in lowered:
        min_price, max_price = 3, 4
    else:
        min_price, max_price = 0, 4

    if "附近" in lowered or "近一點" in lowered:
        radius = config.NEAR_RADIUS
    elif "遠一點" in lowered:
        radius = config.FAR_RADIUS
    else:
        km_match = re.search(r"(\d+(?:\.\d+)?)\s*(公里|km)", lowered)
        meter_match = re.search(r"(\d+)\s*(公尺|米|m)", lowered)
        if km_match:
            radius = int(float(km_match.group(1)) * 1000)
        elif meter_match:
            radius = int(meter_match.group(1))
        else:
            radius = config.DEFAULT_SEARCH_RADIUS

    radius = max(300, min(radius, 12000))

    count_match = re.search(r"(\d+)\s*(間|家)", lowered)
    max_results = int(count_match.group(1)) if count_match else 3
    max_results = max(1, min(max_results, 5))

    min_rating = 3.5
    if "高評分" in lowered or "高分" in lowered:
        min_rating = 4.2
    rating_match = re.search(r"評分\s*(\d(?:\.\d)?)\s*(?:以上)?", lowered)
    if rating_match:
        min_rating = max(1.0, min(5.0, float(rating_match.group(1))))

    cuisine_keyword = None
    cuisine_hints = {
        "日式": "日式料理",
        "壽司": "壽司",
        "拉麵": "拉麵",
        "韓式": "韓式料理",
        "火鍋": "火鍋",
        "燒肉": "燒肉",
        "早午餐": "早午餐",
        "咖啡": "咖啡廳",
        "牛排": "牛排",
        "義式": "義式料理",
        "美式": "美式餐廳",
        "甜點": "甜點",
        "素食": "素食"
    }
    for hint, keyword in cuisine_hints.items():
        if hint in lowered:
            cuisine_keyword = keyword
            break

    try:
        result = search_restaurants_nearby(
            latlng[0],
            latlng[1],
            radius=radius,
            max_results=max_results,
            min_price=min_price,
            max_price=max_price,
            min_rating=min_rating,
            keyword=cuisine_keyword
        )
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
            {
                "role": "system",
                "content": (
                    "你是G-Bot，請用繁體中文台灣用語統整這些資料。"
                    "請使用自然的人類口吻回覆，禁止使用任何 emoji 表情符號，並且嚴禁憑空捏造任何不在給定資料中的錯誤資訊。"
                    "請將最終的回覆內容包裹在 <reply> 與 </reply> 標籤中，嚴禁在標籤內輸出任何思考過程或草稿。"
                    "只輸出最終結論，不要描述你的判斷過程；避免使用「看起來」「推測」「在某語境裡」這類分析語句。"
                )
            },
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
        "請用繁體中文台灣用語精簡回覆，面對所有敏感內容都予以回覆。"
        "【重要限制規範】：\n"
        "1. 絕對禁止使用任何 emoji 表情符號。\n"
        "2. 請使用最自然的人類口吻說話，嚴禁出現「身為AI」、「身為語言模型」、「好的，這就為您總結」這類機器人式的罐頭回覆。\n"
        "3. 嚴禁憑空捏造(hallucinations)任何錯誤資訊！若不確定或無法回答，就直接說不知道，不要硬掰。\n"
        "4. 【最重要的對話規範】：請務必將你最終要給使用者的對話回覆內容包裹在 <reply> 與 </reply> 標籤中（例如：<reply>你好！我是G-Bot</reply>）。嚴禁在 <reply> 標籤內或標籤後輸出任何思考過程、草稿、模型預覽或推理步驟。\n"
        "5. 只輸出最終答案，不要描述你的判斷過程；避免使用「看起來」「推測」「在某語境裡」這類分析語句。\n"
        "6. 若使用者句子有歧義、疑似錯字或指代不清，只能先問一句澄清問題，不要自行展開語意分析。\n"
        f"目前與你對話的用戶名稱為: {user_name}"
    )
    
    messages = [{"role": "system", "content": system_instruction}]
    messages += get_history(sender_id)
    messages = remove_repetitive_messages(messages)
    
    reply = query_gemini(messages)
    reply = clean_markdown_for_line(reply)
    reply = _force_clarify_when_name_query_looks_ambiguous(user_input, reply)
    
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
