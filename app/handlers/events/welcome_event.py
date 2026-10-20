from app.utils.line_utils import reply_message
from app.utils.logger import setup_logger
from app.views.line_menus import build_group_welcome_message, build_welcome_message

logger = setup_logger("welcome_event")


def handle_follow(event):
    """使用者加好友時打招呼；解除封鎖的人改說歡迎回來。"""
    is_unblocked = bool(getattr(getattr(event, "follow", None), "is_unblocked", False))
    reply_message(event.reply_token, build_welcome_message(is_unblocked))


def handle_join(event):
    """被拉進群組或聊天室時自我介紹。"""
    reply_message(event.reply_token, build_group_welcome_message())
