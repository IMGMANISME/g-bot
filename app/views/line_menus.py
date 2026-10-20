from linebot.v3.messaging import (
    LocationAction,
    MessageAction,
    PostbackAction,
    QuickReply,
    QuickReplyItem as LineQuickReplyItem,
    TextMessage,
)
from app.repositories.user_repository import get_user_state
from app.tools.base import QuickReplyItem

LINE_TEXT_LIMIT = 5000

def create_quick_reply_buttons(items: list) -> QuickReply:
    buttons = [LineQuickReplyItem(action=MessageAction(label=label, text=text))
               for label, text in items]
    return QuickReply(items=buttons)

def _button_action(item: QuickReplyItem):
    if item.data is not None:
        # Postback：聊天室顯示按鈕文字，程式收到 data 直接處理
        return PostbackAction(label=item.label, data=item.data, display_text=item.label)
    if item.text is None:
        return LocationAction(label=item.label)
    return MessageAction(label=item.label, text=item.text)


def build_reply_message(text: str, quick_replies: list[QuickReplyItem]) -> TextMessage:
    """文字回覆，可附快速回覆按鈕：一般文字、Postback（data）、傳送位置（text 與 data 都是 None）。"""
    buttons = [LineQuickReplyItem(action=_button_action(item)) for item in quick_replies[:13]]
    return TextMessage(
        text=text[:LINE_TEXT_LIMIT],
        quick_reply=QuickReply(items=buttons) if buttons else None,
    )

def build_quick_intro_message(event, sender_id: str) -> TextMessage:
    state = get_user_state(sender_id)
    source_type = event.source.type
    
    base_items = [("幫助", "#幫助"), ("功能", "#功能"), ("設定", "我的設定")]
    if source_type == "group":
        if "mention" in state:
            items = base_items + [("吃什麼？", "@G-bot 吃什麼?"), ("我的提醒", "@G-bot 我的提醒")]
        else:
            items = base_items + [("吃什麼？", "@G-bot 吃什麼?"), ("我的提醒", "我的提醒")]
    else:
        items = base_items + [("吃什麼？", "吃什麼?"), ("我的提醒", "我的提醒")]
    
    return TextMessage(
        text="請選擇你想做的事 👇",
        quick_reply=create_quick_reply_buttons(items)
    )

def build_quick_help_message(event) -> TextMessage:
    source_type = event.source.type
    
    if source_type == "group":
        help_text = ("🛠️ 可用指令：\n• #選單 - 出示選單\n• #狀態 - 查看目前回話狀態\n• #功能 - 查看相關功能\n• #安靜 - 停止對話\n• #說話 - 恢復回應\n• #標記 - 只在被標記時回覆\n• #都回 - 會回覆所有訊息\n• 我的設定 - 查看目前設定\n• 地震通知開/關、地震門檻 4.5\n• #幫助 - 顯示說明")
        items = [("選單", "#選單"), ("狀態", "#狀態"), ("功能", "#功能"), ("設定", "我的設定"), ("安靜", "#安靜"), ("說話", "#說話"), ("標記", "#標記"), ("都回", "#都回")]
    else:
        help_text = ("🛠️ 可用指令：\n• #選單 - 出示選單\n• #狀態 - 查看目前回話狀態\n• #功能 - 查看相關功能\n• #安靜 - 停止對話\n• #說話 - 恢復回應\n• 我的設定 - 查看目前設定\n• 地震通知開/關、地震門檻 4.5\n• #幫助 - 顯示說明")
        items = [("選單", "#選單"), ("狀態", "#狀態"), ("功能", "#功能"), ("設定", "我的設定"), ("安靜", "#安靜"), ("說話", "#說話")]
    
    return TextMessage(text=help_text, quick_reply=create_quick_reply_buttons(items))


# --- 主動引導 ---

def mention_prefix(state: str) -> str:
    """標記模式下，按鈕送出的文字要加上 @G-bot，否則我不會回覆。"""
    return "@G-bot " if "mention" in state else ""


def build_welcome_message(is_unblocked: bool = False) -> TextMessage:
    """被加好友時的招呼；解除封鎖的人改說歡迎回來。"""
    greeting = "歡迎回來！有需要隨時叫我，" if is_unblocked else "嗨，我是 G-Bot！直接跟我聊天就可以，"
    text = (
        f"{greeting}也可以這樣用我：\n\n"
        "☀️ 問天氣：「高雄明天會下雨嗎」\n"
        "⏰ 設提醒：「明天早上八點提醒我開會」\n"
        "🍜 找吃的：先傳位置給我，再問「附近有什麼好吃的」\n"
        "🌍 地震速報：輸入「地震通知開」，有感地震馬上通知你\n\n"
        "想看所有指令，輸入「#幫助」。"
    )
    return build_reply_message(text, [
        QuickReplyItem("台北天氣", "台北天氣"),
        QuickReplyItem("10 分鐘後提醒我", "10分鐘後提醒我喝水"),
        QuickReplyItem("📍 傳送位置"),
        QuickReplyItem("幫助", "#幫助"),
    ])


def build_group_welcome_message() -> TextMessage:
    """被拉進群組或聊天室時的自我介紹。"""
    text = (
        "大家好，我是 G-Bot！\n\n"
        "可以問我天氣、請我設提醒，或傳位置後問我附近吃什麼。"
        "想收地震速報的話，輸入「地震通知開」。\n"
        "目前群組裡的每則訊息我都會回，覺得太吵的話輸入「#標記」，"
        "我就只在有人叫「@G-bot」時才回覆。\n\n"
        "想看所有指令，輸入「#幫助」。"
    )
    return build_reply_message(text, [
        QuickReplyItem("只在被叫時回", "#標記"),
        QuickReplyItem("台北天氣", "台北天氣"),
        QuickReplyItem("幫助", "#幫助"),
    ])


def build_location_received_message(prefix: str) -> TextMessage:
    """收到位置後，提供找餐廳的快捷按鈕。"""
    call = "標記我並問" if prefix else "直接問我"
    text = f"📍 收到你的位置了！想吃什麼{call}，例如「附近有什麼好吃的」「便宜的拉麵」。"
    return build_reply_message(text, [
        QuickReplyItem("附近吃什麼", f"{prefix}附近有什麼好吃的"),
        QuickReplyItem("便宜的", f"{prefix}吃什麼 便宜"),
        QuickReplyItem("近一點", f"{prefix}吃什麼 近一點"),
        QuickReplyItem("拉麵", f"{prefix}吃什麼 拉麵"),
    ])
