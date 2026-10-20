from app.realtime_search import get_realtime_info
from app.repositories.message_repository import save_message


def get_realtime_reply(*, memory_id: str, user_input: str, memory_user_input: str) -> str:
    # 天氣與時間資料本身已整理成可讀格式，直接回覆，不再交給模型改寫
    reply = get_realtime_info(user_input)
    save_message(memory_id, "user", memory_user_input)
    save_message(memory_id, "assistant", reply)
    return reply
