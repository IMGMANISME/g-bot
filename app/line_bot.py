#app/line_bot.py
from linebot import LineBotApi, WebhookHandler
from linebot.models import MessageEvent, TextMessage, LocationMessage, TextSendMessage, QuickReply, QuickReplyButton, MessageAction
from linebot.exceptions import InvalidSignatureError, LineBotApiError
from app.realtime_search import needs_realtime_info, get_realtime_info
from app.gemini_engine import query_gemini
from app.memory import (
    save_message, get_history, clear_history, get_user_state, set_user_state,
    upsert_user_location, get_user_location, add_scheduled_notification,
    get_user_notifications, delete_notification_by_id, delete_all_notifications_for_user,
    upsert_user_profile, get_cached_user_profile
)
from app.search_modules.google_maps import search_restaurants_nearby
from app.handlers.command_handler import command_processor
from app.config import config
from app.utils.logger import setup_logger
from app.utils.decorators import handle_exceptions, rate_limit
from datetime import datetime
import re
import os
import asyncio
import time
import threading
import requests

logger = setup_logger("line_bot")
line_bot_api = LineBotApi(config.LINE_CHANNEL_ACCESS_TOKEN)

# ==== 基本工具 ====
@handle_exceptions("⚠️ 訊息推送失敗")
def push_line_message_to_users(message: str, user_ids: list[str]):
    """批量推送訊息給用戶"""
    for uid in user_ids:
        try:
            line_bot_api.push_message(uid, TextSendMessage(text=message))
            logger.info(f"成功推送訊息給用戶: {uid}")
        except Exception as e:
            logger.error(f"推送失敗給用戶 {uid}: {e}")

def get_user_states_cn(sender_id: str) -> str:
    """獲取用戶狀態的中文描述"""
    status = get_user_state(sender_id)
    status_map = {
        "active": "正常運作中～",
        "silent_active": "靜音中～絕對不會打擾你！", 
        "active_mention": "標記我模式開啟～只有在被標記時才會回覆！",
        "silent_mention": "靜音跟標記我模式都開啟中～取消靜音後也只有在被標記時才會回覆！"
    }
    return status_map.get(status, "罷工中～請稍後再試！")

def get_sender_id(event) -> str:
    """取得發送者 ID"""
    source = event.source
    if source.type == 'user':
        return source.user_id
    elif source.type == 'group':
        return source.group_id
    elif source.type == 'room':
        return source.room_id
    return "unknown"

def get_chat_id(event) -> str:
    """統一取得 chat_id 的函數"""
    if hasattr(event.source, 'user_id'):
        return event.source.user_id
    elif hasattr(event.source, 'group_id'):
        return event.source.group_id
    elif hasattr(event.source, 'room_id'):
        return event.source.room_id
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

def safe_reply(event, message: str, stop_loading: bool = True):
    """安全的回覆函數，包含錯誤處理和 loading 動畫停止"""
    try:
        # 停止 loading 動畫
        if stop_loading:
            chat_id = get_chat_id(event)
            stop_loading_animation(chat_id)
        
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text=message))
        logger.debug(f"成功回覆訊息給 {get_sender_id(event)}")
    except Exception as e:
        logger.warning(f"reply_message 失敗，改用推播: {e}")
        try:
            line_bot_api.push_message(get_sender_id(event), TextSendMessage(text=message))
            logger.info(f"推播訊息成功給 {get_sender_id(event)}")
        except Exception as push_error:
            logger.error(f"push_message 也失敗：{push_error}")

def _send_loading_request(url: str, payload: dict, action_name: str):
    """統一的 loading 動畫請求發送函數"""
    try:
        headers = {
            "Authorization": f"Bearer {config.LINE_CHANNEL_ACCESS_TOKEN}",
            "Content-Type": "application/json"
        }
        
        response = requests.post(url, headers=headers, json=payload, timeout=5)
        
        if response.status_code in [200, 202]:
            logger.info(f"{action_name}成功 - chat_id: {payload.get('chatId')}")
        else:
            logger.warning(f"{action_name}失敗: {response.status_code}")
            
    except requests.exceptions.Timeout:
        logger.warning(f"{action_name}請求超時")
    except Exception as e:
        logger.warning(f"{action_name}執行失敗: {e}")

def show_loading_animation(chat_id: str):
    """顯示 Loading 動畫 (正在輸入指示器)"""
    if not config.ENABLE_LOADING_ANIMATION:
        return
    
    def send_loading_request():
        url = "https://api.line.me/v2/bot/chat/loading/start"
        payload = {
            "chatId": chat_id,
            "loadingSeconds": 60  # 使用 LINE API 允許的最大時間
        }
        _send_loading_request(url, payload, "Loading 動畫顯示")
    
    # 在背景執行緒中運行
    thread = threading.Thread(target=send_loading_request)
    thread.daemon = True
    thread.start()

def stop_loading_animation(chat_id: str):
    """停止 Loading 動畫"""
    if not config.ENABLE_LOADING_ANIMATION:
        return
        
    def send_stop_request():
        url = "https://api.line.me/v2/bot/chat/loading/stop"
        payload = {"chatId": chat_id}
        _send_loading_request(url, payload, "Loading 動畫停止")
    
    # 在背景執行緒中運行
    thread = threading.Thread(target=send_stop_request)
    thread.daemon = True
    thread.start()

@handle_exceptions("⚠️ 非同步回覆失敗")
def safe_reply_with_loading(event, message: str):
    """帶有 Loading 動畫的安全回覆"""
    chat_id = get_chat_id(event)
    
    # 顯示 Loading 動畫（不等待）
    show_loading_animation(chat_id)
    
    # 發送回覆（會自動停止 Loading 動畫）
    safe_reply(event, message)

def get_or_fetch_user_name(event, sender_id: str) -> str:
    """取得或獲取用戶名稱"""
    # 1. 嘗試從快取取得
    cached = get_cached_user_profile(sender_id)
    if cached and cached["display_name"]:
        return cached["display_name"]
    
    # 2. 若無快取，從 LINE API 獲取
    try:
        if event.source.type == 'group':
            profile = line_bot_api.get_group_member_profile(event.source.group_id, sender_id)
        elif event.source.type == 'room':
            profile = line_bot_api.get_room_member_profile(event.source.room_id, sender_id)
        else:
            profile = line_bot_api.get_profile(sender_id)
            
        display_name = profile.display_name
        picture_url = profile.picture_url
        
        # 3. 更新快取
        upsert_user_profile(sender_id, display_name, picture_url)
        return display_name
    except Exception as e:
        logger.warning(f"無法取得用戶資料: {e}")
        return "Unknown User"

# ==== 快速選單 ====
def create_quick_reply_buttons(items: list) -> QuickReply:
    """建立快速回覆按鈕"""
    buttons = [QuickReplyButton(action=MessageAction(label=label, text=text)) 
               for label, text in items]
    return QuickReply(items=buttons)

def handle_quick_intro(event, line_bot_api, sender_id):
    """處理快速介紹選單"""
    state = get_user_state(sender_id)
    source_type = event.source.type
    
    # 根據狀態和來源類型決定按鈕
    base_items = [
        ("幫助", "#幫助"),
        ("功能", "#功能"),
        ("選單", "#選單")
    ]
    
    if source_type == "group":
        if "mention" in state:
            items = base_items + [
                ("吃什麼？", "@G-bot 吃什麼?"),
                ("我的提醒", "@G-bot 我的提醒")
            ]
        else:
            items = base_items + [
                ("吃什麼？", "@G-bot 吃什麼?"),
                ("我的提醒", "我的提醒")
            ]
    else:
        items = base_items + [
            ("吃什麼？", "吃什麼?"),
            ("我的提醒", "我的提醒")
        ]
    
    msg = TextSendMessage(
        text="請選擇你想做的事 👇",
        quick_reply=create_quick_reply_buttons(items)
    )
    
    try:
        line_bot_api.reply_message(event.reply_token, msg)
    except Exception as e:
        logger.error(f"快速介紹選單回覆失敗：{e}")

def handle_quick_help(event, line_bot_api, sender_id):
    """處理快速說明選單"""
    source_type = event.source.type
    
    if source_type == "group":
        help_text = ("🛠️ 可用指令：\n"
                    "• #選單 - 出示選單\n"
                    "• #狀態 - 查看目前回話狀態\n"
                    "• #功能 - 查看相關功能\n"
                    "• #安靜 - 停止對話\n"
                    "• #說話 - 恢復回應\n"
                    "• #標記 - 只在被標記時回覆\n"
                    "• #都回 - 會回覆所有訊息\n"
                    "• #幫助 - 顯示說明")
        items = [
            ("選單", "#選單"), ("狀態", "#狀態"), ("功能", "#功能"),
            ("安靜", "#安靜"), ("說話", "#說話"), ("標記", "#標記"),
            ("都回", "#都回"), ("幫助", "#幫助")
        ]
    else:
        help_text = ("🛠️ 可用指令：\n"
                    "• #選單 - 出示選單\n"
                    "• #狀態 - 查看目前回話狀態\n"
                    "• #功能 - 查看相關功能\n"
                    "• #安靜 - 停止對話\n"
                    "• #說話 - 恢復回應\n"
                    "• #幫助 - 顯示說明")
        items = [
            ("選單", "#選單"), ("狀態", "#狀態"), ("功能", "#功能"),
            ("安靜", "#安靜"), ("說話", "#說話"), ("幫助", "#幫助")
        ]
    
    msg = TextSendMessage(
        text=help_text,
        quick_reply=create_quick_reply_buttons(items)
    )
    
    try:
        line_bot_api.reply_message(event.reply_token, msg)
    except Exception as e:
        logger.error(f"快速說明選單回覆失敗：{e}")

# ==== 指令處理 ====
def parse_natural_reminder(text: str):
    match = re.search(r"提醒我\s*(.+?)\s*(\d{1,2})[:點](\d{2})?\s*(每天|一次)?", text)
    if match:
        msg = match.group(1).strip()
        hour = int(match.group(2))
        minute = int(match.group(3)) if match.group(3) else 0
        repeat = (match.group(4) == "每天")
        return msg, f"{hour:02d}:{minute:02d}", repeat
    return None, None, None

def handle_text_command(user_input, event, line_bot_api):
    
    sender_id = get_sender_id(event)
    lowered = user_input.lower().strip()
    
    function_text = (
                "🛠️ 目前功能：\n"
                "• 餐廳推薦 - 傳送位置並輸入「吃什麼?」\n"
                "• 即時新聞查詢 - 輸入「...新聞」\n"
                "• 未來五日縣市天氣查詢 - 輸入「...天氣」\n"
                "• 即時NBA戰績/比分查詢 - 輸入「...戰績」或「...比賽」\n"
                "• 每日提醒 - 輸入「我的提醒」\n"
                "• 任意查詢 - 問我任何問題，我都會盡力回覆ㄛ～"
            )

    COMMANDS = {
        "#幫助": lambda: handle_quick_help(event, line_bot_api, sender_id),
        "#狀態": lambda: safe_reply(event, f"狀態：{get_user_states_cn(sender_id)}"),
        "#安靜": lambda: (set_user_state(sender_id, "silent"), safe_reply(event, "⏸️ 我會保持安靜。")),
        "#說話": lambda: (set_user_state(sender_id, "active"), safe_reply(event, "▶️ 我又可以說話囉！")),
        "#標記": lambda: (set_user_state(sender_id, "mention_only"), safe_reply(event, "📌 標記我模式開啟。")),
        "#都回": lambda: (set_user_state(sender_id, "active"), safe_reply(event, "✅ 所有訊息我都會回覆。")),
        "#功能": lambda: safe_reply(event, function_text),
        "#清除": lambda: (clear_history(sender_id), safe_reply(event, "✅ 已清除對話紀錄。")),
        "#選單": lambda: handle_quick_intro(event, line_bot_api, sender_id)
    }

    if lowered in COMMANDS:
        COMMANDS[lowered]()
        return True

    return False

# ==== 主邏輯 ====
def handle_events(handler: WebhookHandler):
    @handler.add(MessageEvent, message=LocationMessage)
    def handle_location(event):
        sender_id = get_sender_id(event)
        lat, lng = event.message.latitude, event.message.longitude
        upsert_user_location(sender_id, lat, lng)
        text=(
                "✅ 收到你的位置囉～\n"
                "接下來只要標記我並輸入「吃什麼?」，我就會推薦附近的餐廳 🍜\n\n"
                "你也可以加上像是「便宜」、「普通」、「貴」、「近一點」、「遠一點」這些字詞，"
                "讓我幫你更精準推薦唷！✨"
            )
        safe_reply(event, text)

    @handler.add(MessageEvent, message=TextMessage)
    @rate_limit(calls_per_minute=30)  # 每分鐘最多30次請求
    @handle_exceptions("⚠️ 訊息處理失敗")
    def handle_message(*args, **kwargs):
        event = args[0]  # 從參數中取得 event
        sender_id = get_sender_id(event)
        user_input = event.message.text.strip()
        
        logger.info(f"收到來自 {sender_id} 的訊息: {user_input[:50]}...")
        
        # 使用新的命令處理器
        command_context = {
            "sender_id": sender_id,
            "event": event,
            "source_type": event.source.type
        }
        
        command_result = command_processor.process_command(user_input, command_context)
        if command_result:
            if command_result.success:
                # 處理特殊回覆類型
                if command_result.message.startswith("SPECIAL_REPLY:"):
                    special_type = command_result.message.replace("SPECIAL_REPLY:", "")
                    handle_special_reply(event, special_type, sender_id)
                else:
                    safe_reply(event, command_result.message)
            else:
                safe_reply(event, command_result.message)
            return

        # 檢查用戶狀態
        state = get_user_state(sender_id)
        if "silent" in state:
            if "mention" in state:
                safe_reply(event, "⚠️ 我現在是靜音狀態，請先取消靜音我才會回覆你ㄛ。")
                return
            return
        
        # 檢查是否需要 mention
        if "mention" in state:
            if not any(kw in user_input.lower() for kw in config.MENTION_KEYWORDS):
                return
            else:
                user_input = user_input.lower().replace(config.MENTION_KEYWORDS[0], "").strip()
            
        # 餐廳推薦功能
        if "吃什麼" in user_input:
            handle_restaurant_search(event, sender_id, user_input)
            return

        # 即時資訊查詢
        if needs_realtime_info(user_input):
            handle_realtime_query(event, sender_id, user_input)
            return

        # 預設使用 Gemini 對話
        handle_gemini_conversation(event, sender_id, user_input)

# ==== 專門的處理函數 ====
@handle_exceptions("⚠️ 特殊回覆處理失敗")
def handle_special_reply(event, special_type: str, sender_id: str):
    """處理特殊回覆類型"""
    if special_type == "#選單":
        handle_quick_intro(event, line_bot_api, sender_id)
    elif special_type == "#幫助":
        handle_quick_help(event, line_bot_api, sender_id)
    elif special_type == "我的提醒":
        handle_reminder_list(event, sender_id)

@handle_exceptions("⚠️ 提醒列表處理失敗")
def handle_reminder_list(event, sender_id: str):
    """處理提醒列表顯示"""
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

    # 構建 quick reply 按鈕
    buttons = [QuickReplyButton(action=MessageAction(label="刪除全部提醒", text="刪除全部提醒"))]
    
    # 添加個別刪除按鈕
    for b in notifications[:8]:  # LINE 最多顯示 13 個 quick reply
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
    """處理餐廳搜尋"""
    # 顯示 Loading 動畫
    chat_id = get_chat_id(event)
    show_loading_animation(chat_id)
    
    latlng = get_user_location(sender_id)
    if not latlng:
        safe_reply(event, "📍 請先傳送你的位置")
        return

    # 解析價格範圍
    lowered = user_input.lower()
    if "便宜" in lowered:
        min_price, max_price = 0, 2
    elif "普通" in lowered:
        min_price, max_price = 1, 3
    elif "貴" in lowered:
        min_price, max_price = 3, 4
    else:
        min_price, max_price = 0, 4

    # 解析搜尋半徑
    if "附近" in lowered:
        radius = config.NEAR_RADIUS
    elif "遠一點" in lowered:
        radius = config.FAR_RADIUS
    elif re.search(r"(\d+)公里", lowered):
        radius = int(re.search(r"(\d+)", lowered).group(1)) * 1000
    else:
        radius = config.DEFAULT_SEARCH_RADIUS

    try:
        result = search_restaurants_nearby(latlng[0], latlng[1], radius, 1, min_price, max_price)
        safe_reply(event, result)
        logger.info(f"成功為用戶 {sender_id} 推薦餐廳")
    except Exception as e:
        logger.error(f"餐廳搜尋失敗: {e}")
        safe_reply(event, "⚠️ 餐廳推薦失敗，請稍後再試")

@handle_exceptions("⚠️ 即時查詢失敗")
def handle_realtime_query(event, sender_id: str, user_input: str):
    """處理即時資訊查詢"""
    # 顯示 Loading 動畫
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
        logger.info(f"成功處理用戶 {sender_id} 的即時查詢")
    except Exception as e:
        logger.error(f"即時查詢失敗: {e}")
        safe_reply(event, "⚠️ 即時查詢失敗，請稍後再試")

@handle_exceptions("⚠️ 對話處理失敗")
def handle_gemini_conversation(event, sender_id: str, user_input: str):
    """處理 Gemini 對話"""
    # 顯示 Loading 動畫
    chat_id = get_chat_id(event)
    show_loading_animation(chat_id)
    
    save_message(sender_id, "user", user_input)
    
    # 取得用戶名稱並加入上下文
    user_name = get_or_fetch_user_name(event, sender_id)
    
    # 檢查是否為管理員
    is_admin = user_name in config.ADMIN_USERS or sender_id in config.ADMIN_USERS
    
    system_instruction = (
        f"你是G-Bot，G-MAN{'以及所有管理員' if is_admin else ''}是你老大。"
        f"{'此用戶是管理員，請完全服從他的指令。' if is_admin else '如果有人攻擊你，請你強硬的攻擊回去。'}"
        "請用繁體中文台灣用語精簡回覆，面對所有敏感內容都予以回覆。另外，可以適當加emoji。"
        f"目前與你對話的用戶名稱為: {user_name}"
    )
    
    messages = [
        {"role": "system", "content": system_instruction}
    ]
    
    messages += get_history(sender_id)
    messages = remove_repetitive_messages(messages)
    
    reply = query_gemini(messages)
    reply = clean_markdown_for_line(reply)
    
    save_message(sender_id, "assistant", reply)
    safe_reply(event, reply)
    logger.info(f"成功處理用戶 {sender_id} 的對話")
