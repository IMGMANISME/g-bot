from app.utils.line_utils import get_sender_id, safe_reply
from app.repositories.user_repository import upsert_user_location

def handle_location(event):
    sender_id = get_sender_id(event)
    lat, lng = event.message.latitude, event.message.longitude
    upsert_user_location(sender_id, lat, lng)
    text = (
        "✅ 收到你的位置囉～\n"
        "接下來只要標記我並輸入「吃什麼?」，我就會推薦附近的餐廳 🍜\n\n"
        "你也可以加上像是「便宜」、「普通」、「貴」、「近一點」、「遠一點」這些字詞，"
        "讓我幫你更精準推薦唷！✨"
    )
    safe_reply(event, text)
