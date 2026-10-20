from app.repositories.user_repository import get_user_state, upsert_user_location
from app.utils.line_utils import get_chat_id, get_sender_id, safe_reply_message
from app.views.line_menus import build_location_received_message, mention_prefix

def handle_location(event):
    sender_id = get_sender_id(event)
    lat, lng = event.message.latitude, event.message.longitude
    upsert_user_location(sender_id, lat, lng)
    prefix = mention_prefix(get_user_state(get_chat_id(event)))
    safe_reply_message(event, build_location_received_message(prefix))
