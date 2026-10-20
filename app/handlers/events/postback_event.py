from app.repositories.user_repository import get_user_state
from app.tools.base import ToolContext, run_action
from app.utils.line_utils import get_chat_id, get_sender_id, safe_reply_message
from app.utils.logger import setup_logger
from app.utils.time_utils import now_taipei
from app.views.line_menus import build_reply_message, mention_prefix

logger = setup_logger("postback_event")


def handle_postback(event):
    """按鈕的 Postback：交給對應的按鈕動作處理，直接回覆，不經過模型。"""
    chat_id = get_chat_id(event)
    ctx = ToolContext(
        chat_id=chat_id,
        sender_id=get_sender_id(event),
        user_text="",
        now=now_taipei(),
        mention_prefix=mention_prefix(get_user_state(chat_id)),
    )
    result = run_action(event.postback.data, ctx)
    text = f"{result.fallback_text}\n\n{result.attachment}" if result.attachment else result.fallback_text
    safe_reply_message(event, build_reply_message(text, result.quick_replies))
