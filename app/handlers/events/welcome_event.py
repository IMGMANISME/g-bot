from app.utils.line_utils import line_bot_api
from app.utils.logger import setup_logger
from app.views.line_menus import build_group_welcome_message, build_welcome_message

logger = setup_logger("welcome_event")


def handle_follow(event):
    """使用者加好友（或解除封鎖）時打招呼。"""
    line_bot_api.reply_message(event.reply_token, build_welcome_message())


def handle_join(event):
    """被拉進群組或聊天室時自我介紹。"""
    line_bot_api.reply_message(event.reply_token, build_group_welcome_message())
