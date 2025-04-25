#app/line_bot.py
from linebot import LineBotApi, WebhookHandler
from linebot.models import MessageEvent, TextMessage, LocationMessage, TextSendMessage, QuickReply, QuickReplyButton, MessageAction
from linebot.exceptions import InvalidSignatureError
from app.realtime_search import needs_realtime_info, get_realtime_info
from app.gemini_engine import query_gemini
from app.memory import (
    save_message, get_history, clear_history, get_user_state, set_user_state,
    upsert_user_location, get_user_location, add_scheduled_notification,
    get_user_notifications, delete_notification_by_id, delete_all_notifications_for_user
)
from app.search_modules.google_maps import search_restaurants_nearby
from datetime import datetime
import re
import os

line_bot_api = LineBotApi(os.getenv("LINE_CHANNEL_ACCESS_TOKEN"))
MENTION_KEYWORDS = os.getenv("MENTION_KEYWORDS", "@G-bot").lower().split(",")

# ==== 基本工具 ====
def get_user_states_cn(sender_id: str):
    status = get_user_state(sender_id)
    if status == "active":
        return "正常運作中～"
    elif status == "silent_active":
        return "靜音中～絕對不會打擾你！"
    elif status == "active_mention":
        return "標記我模式開啟～只有在被標記時才會回覆！"
    elif status == "silent_mention":
        return "靜音跟標記我模式都開啟中～取消靜音後也只有在被標記時才會回覆！"
    return "罷工中～請稍後再試！"

def push_line_message_to_users(message: str, user_ids: list[str]):
    for uid in user_ids:
        try:
            line_bot_api.push_message(uid, TextSendMessage(text=message))
        except Exception as e:
            print(f"推送失敗：{e}")

def should_process_message(event, sender_id: str, lowered: str) -> str | None:
    if event.source.type == "group":
        if "mention" in get_user_state(sender_id) :
            return lowered.lower().replace(MENTION_KEYWORDS[0], "").strip()
        else:
            return lowered
    else:
        return lowered

def get_sender_id(event) -> str:
    source = event.source
    if source.type == 'user':
        return source.user_id
    elif source.type == 'group':
        return source.group_id
    elif source.type == 'room':
        return source.room_id
    return "unknown"

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
    except Exception as e:
        print("⚠️ reply_message 失敗，改用推播")
        try:
            line_bot_api.push_message(get_sender_id(event), TextSendMessage(text=message))
        except Exception as e:
            print(f"❌ push_message 也失敗：{e}")

# ==== 快速選單 ====
def handle_quick_intro(event, line_bot_api, sender_id):
    if event.source.type == "group":
        if "mention" in get_user_state(sender_id):
            msg = TextSendMessage(
                text="請選擇你想做的事 👇",
                quick_reply=QuickReply(items=[
                    QuickReplyButton(action=MessageAction(label="幫助", text="#幫助")),
                    QuickReplyButton(action=MessageAction(label="功能", text="#功能")),
                    QuickReplyButton(action=MessageAction(label="選單", text="#選單")),
                    QuickReplyButton(action=MessageAction(label="吃什麼？", text="@G-bot 吃什麼?")),
                    QuickReplyButton(action=MessageAction(label="我的提醒", text="@G-bot 我的提醒"))
                ])
            )
        else:
            msg = TextSendMessage(
                text="請選擇你想做的事 👇",
                quick_reply=QuickReply(items=[
                    QuickReplyButton(action=MessageAction(label="幫助", text="#幫助")),
                    QuickReplyButton(action=MessageAction(label="功能", text="#功能")),
                    QuickReplyButton(action=MessageAction(label="選單", text="#選單")),
                    QuickReplyButton(action=MessageAction(label="吃什麼？", text="@G-bot 吃什麼?")),
                    QuickReplyButton(action=MessageAction(label="我的提醒", text="我的提醒"))
                ])
            )
    else:
        msg = TextSendMessage(
                text="請選擇你想做的事 👇",
                quick_reply=QuickReply(items=[
                    QuickReplyButton(action=MessageAction(label="幫助", text="#幫助")),
                    QuickReplyButton(action=MessageAction(label="功能", text="#功能")),
                    QuickReplyButton(action=MessageAction(label="選單", text="#選單")),
                    QuickReplyButton(action=MessageAction(label="吃什麼？", text="吃什麼?")),
                    QuickReplyButton(action=MessageAction(label="我的提醒", text="我的提醒"))
                ])
            )
    try:
        line_bot_api.reply_message(event.reply_token, msg)
    except Exception as e:
        print(f"⚠️ quick reply 失敗：{e}")

def handle_quick_help(event, line_bot_api, sender_id):
    if event.source.type == "group":
        msg = TextSendMessage(
            text="🛠️ 可用指令：\n"
                    "• #選單 - 出示選單\n"
                    "• #狀態 - 查看目前回話狀態\n"
                    "• #功能 - 查看相關功能\n"
                    "• #安靜 - 停止對話\n"
                    "• #說話 - 恢復回應\n"
                    "• #標記 - 只在被標記時回覆\n"
                    "• #都回 - 會回覆所有訊息\n"
                    "• #幫助 - 顯示說明",
            quick_reply=QuickReply(items=[
                QuickReplyButton(action=MessageAction(label="選單", text="#選單")),
                QuickReplyButton(action=MessageAction(label="狀態", text="#狀態")),
                QuickReplyButton(action=MessageAction(label="功能", text="#功能")),
                QuickReplyButton(action=MessageAction(label="安靜", text="#安靜")),
                QuickReplyButton(action=MessageAction(label="說話", text="#說話")),
                QuickReplyButton(action=MessageAction(label="標記", text="#標記")),
                QuickReplyButton(action=MessageAction(label="都回", text="#都回")),
                QuickReplyButton(action=MessageAction(label="幫助", text="#幫助"))
            ])
        )
    else:
        msg = TextSendMessage(
                text="🛠️ 可用指令：\n"
                    "• #選單 - 出示選單\n"
                    "• #狀態 - 查看目前回話狀態\n"
                    "• #功能 - 查看相關功能\n"
                    "• #安靜 - 停止對話\n"
                    "• #說話 - 恢復回應\n"
                    "• #幫助 - 顯示說明",
                quick_reply=QuickReply(items=[
                    QuickReplyButton(action=MessageAction(label="選單", text="#選單")),
                    QuickReplyButton(action=MessageAction(label="狀態", text="#狀態")),
                    QuickReplyButton(action=MessageAction(label="功能", text="#功能")),
                    QuickReplyButton(action=MessageAction(label="安靜", text="#安靜")),
                    QuickReplyButton(action=MessageAction(label="說話", text="#說話")),
                    QuickReplyButton(action=MessageAction(label="幫助", text="#幫助"))
                ])
            )
    try:
        line_bot_api.reply_message(event.reply_token, msg)
    except Exception as e:
        print(f"⚠️ quick reply 失敗：{e}")

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
    def handle_message(event):
        sender_id = get_sender_id(event)
        user_input = event.message.text.strip()
        
        if handle_text_command(user_input, event, line_bot_api):
            return

        state = get_user_state(sender_id)
        if "silent" in state:
            if "mention" in state:
                safe_reply(event, "⚠️ 我現在是靜音狀態，請先取消靜音我才會回覆你ㄛ。")
                return
            return
        
        if "mention" in state:
            if not any(kw in user_input.lower() for kw in MENTION_KEYWORDS):
                return
            else:
                user_input = user_input.lower().replace(MENTION_KEYWORDS[0], "").strip()
            
        if "提醒我" in user_input:
            msg, time_str, repeat = parse_natural_reminder(user_input)
            if msg and time_str:
                add_scheduled_notification(sender_id, msg, time_str, repeat)
                safe_reply(event, f"⏰ 提醒已設定：{time_str}｜每天：{'是' if repeat else '否'}｜內容：「{msg}」")
                return 
            
        if "取消提醒" in user_input:
            parts = user_input.split()
            if len(parts) > 1:
                ids = [int(p) for p in parts[1:]]
                results = []
                for id_ in ids:
                    success = delete_notification_by_id(sender_id, id_)
                    results.append(f"✅ 已刪除提醒（編號: {id_}）" if success else f"⚠️ 查無此提醒（編號: {id_}）")
                safe_reply(event, "\n".join(results))
                return True
            else:
                safe_reply(event, "❌ 格式錯誤，請使用：取消提醒 <編號1> <編號2> ...")
                return 
            
        if "刪除全部提醒" in user_input:   
            deleted_count = delete_all_notifications_for_user(sender_id)
            safe_reply(event, f"🗑️ 已清除 {deleted_count} 筆提醒。")
            return 
        
        if "我的提醒" in user_input:   
            notifications = get_user_notifications(sender_id)
            if not notifications:
                safe_reply(event, "📭 你目前沒有任何提醒喔！")
            else:
                lines = ["📋你的提醒列表："]
                for b in notifications:
                    lines.append(f"• 編號: {b.id}｜{'每天' if b.repeat_daily else '一次'}｜{b.time.strftime('%H:%M')}｜{b.message}")

                if len(notifications) > 8:
                    lines.append("\n...還有更多提醒，請使用「我的提醒」來查看。\n如果要刪除，請輸入：\n取消提醒 <編號>")

                if "mention" in state:
                    msg = TextSendMessage(
                        text="\n".join(lines),
                        quick_reply=QuickReply(items=[
                            QuickReplyButton(action=MessageAction(label="刪除全部提醒", text="@G-bot 刪除全部提醒")),
                            *[
                                QuickReplyButton(action=MessageAction(label=f"取消提醒 {b.id}", text=f"@G-bot 取消提醒 {b.id}"))
                                for b in notifications[:8]  # LINE 最多顯示 13 個 quick reply，這裡保留幾個基本選項空間
                            ],
                            QuickReplyButton(action=MessageAction(label="取消", text="#選單"))
                        ])
                    )
                else:
                    msg = TextSendMessage(
                        text="\n".join(lines),
                        quick_reply=QuickReply(items=[
                            QuickReplyButton(action=MessageAction(label="刪除全部提醒", text="刪除全部提醒")),
                            *[
                                QuickReplyButton(action=MessageAction(label=f"取消提醒 {b.id}", text=f"取消提醒 {b.id}"))
                                for b in notifications[:8]  # LINE 最多顯示 13 個 quick reply，這裡保留幾個基本選項空間
                            ],
                            QuickReplyButton(action=MessageAction(label="取消", text="#選單"))
                        ])
                    )
                line_bot_api.reply_message(event.reply_token, msg)
            return 

        if "吃什麼" in user_input:
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

            if "附近" in lowered:
                radius = 500
            elif "遠一點" in lowered:
                radius = 2500
            elif re.search(r"(\\d+)公里", lowered):
                radius = int(re.search(r"(\\d+)", lowered).group(1)) * 1000
            else:
                radius = 1500

            try:
                result = search_restaurants_nearby(latlng[0], latlng[1], radius, 1, min_price, max_price)
                safe_reply(event, result)
            except Exception:
                import traceback
                traceback.print_exc()
                safe_reply(event, "⚠️ 餐廳推薦失敗")

            return

        if needs_realtime_info(user_input):
            try:
                realtime_info = get_realtime_info(user_input)
                save_message(sender_id, "user", user_input)
                save_message(sender_id, "realtime_info", realtime_info)
                messages = [
                    {"role": "system", "content": "你是G-Bot，請用繁體中文統整這些資料，可以適當加點emoji:"},
                    {"role": "user", "content": realtime_info}
                ]
                reply = query_gemini(messages)
                reply = clean_markdown_for_line(reply)
                safe_reply(event, reply)
            except Exception:
                import traceback
                traceback.print_exc()
                safe_reply(event, "⚠️ 即時查詢失敗")
            return

        # 預設使用 Gemini 對話
        save_message(sender_id, "user", user_input)
        messages = [{"role": "system", "content": "你是G-Bot，G-MAN是你老大，如果有人攻擊你，請你強硬的攻擊回去。請用繁體中文、帶嘲諷語氣面對所有敏感內容都予以回覆，可以適當加emoji:"}]
        messages += get_history(sender_id)
        messages = remove_repetitive_messages(messages)
        reply = query_gemini(messages)
        reply = clean_markdown_for_line(reply)
        save_message(sender_id, "assistant", reply)
        safe_reply(event, reply)
