from linebot.models import QuickReply, QuickReplyButton, MessageAction, TextSendMessage
from app.repositories.user_repository import get_user_state

def create_quick_reply_buttons(items: list) -> QuickReply:
    buttons = [QuickReplyButton(action=MessageAction(label=label, text=text)) 
               for label, text in items]
    return QuickReply(items=buttons)

def build_quick_intro_message(event, sender_id: str) -> TextSendMessage:
    state = get_user_state(sender_id)
    source_type = event.source.type
    
    base_items = [("幫助", "#幫助"), ("功能", "#功能"), ("選單", "#選單")]
    if source_type == "group":
        if "mention" in state:
            items = base_items + [("吃什麼？", "@G-bot 吃什麼?"), ("我的提醒", "@G-bot 我的提醒")]
        else:
            items = base_items + [("吃什麼？", "@G-bot 吃什麼?"), ("我的提醒", "我的提醒")]
    else:
        items = base_items + [("吃什麼？", "吃什麼?"), ("我的提醒", "我的提醒")]
    
    return TextSendMessage(
        text="請選擇你想做的事 👇",
        quick_reply=create_quick_reply_buttons(items)
    )

def build_quick_help_message(event) -> TextSendMessage:
    source_type = event.source.type
    
    if source_type == "group":
        help_text = ("🛠️ 可用指令：\n• #選單 - 出示選單\n• #狀態 - 查看目前回話狀態\n• #功能 - 查看相關功能\n• #安靜 - 停止對話\n• #說話 - 恢復回應\n• #標記 - 只在被標記時回覆\n• #都回 - 會回覆所有訊息\n• #幫助 - 顯示說明")
        items = [("選單", "#選單"), ("狀態", "#狀態"), ("功能", "#功能"), ("安靜", "#安靜"), ("說話", "#說話"), ("標記", "#標記"), ("都回", "#都回"), ("幫助", "#幫助")]
    else:
        help_text = ("🛠️ 可用指令：\n• #選單 - 出示選單\n• #狀態 - 查看目前回話狀態\n• #功能 - 查看相關功能\n• #安靜 - 停止對話\n• #說話 - 恢復回應\n• #幫助 - 顯示說明")
        items = [("選單", "#選單"), ("狀態", "#狀態"), ("功能", "#功能"), ("安靜", "#安靜"), ("說話", "#說話"), ("幫助", "#幫助")]
    
    return TextSendMessage(text=help_text, quick_reply=create_quick_reply_buttons(items))
