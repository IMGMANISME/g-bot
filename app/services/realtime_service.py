from app.config import config
from app.gemini_engine import query_gemini
from app.prompt_loader import render_prompt
from app.realtime_search import get_realtime_info
from app.repositories.message_repository import save_message
from app.utils.cache import global_cache
from app.utils.line_utils import clean_markdown_for_line


LAST_REALTIME_QUERY_TTL = 60 * 10


def _last_realtime_query_key(memory_id: str) -> str:
    return f"realtime_last_query:{memory_id}"


def get_realtime_reply(*, memory_id: str, user_input: str, memory_user_input: str) -> str:
    is_detail_request = user_input.strip() == "查更詳細"
    if is_detail_request:
        previous_query = global_cache.get(_last_realtime_query_key(memory_id))
        if not previous_query:
            return "我還沒有上一個即時查詢可以延伸。"
        query_text = f"{previous_query} 更詳細"
    else:
        query_text = user_input
        global_cache.set(_last_realtime_query_key(memory_id), user_input, ttl=LAST_REALTIME_QUERY_TTL)

    realtime_info = get_realtime_info(query_text)
    save_message(memory_id, "user", memory_user_input)
    save_message(memory_id, "realtime_info", realtime_info)

    messages = [
        {
            "role": "system",
            "content": render_prompt(config.SYSTEM_PROMPT_PROFILE, "realtime"),
        },
        {
            "role": "user",
            "content": (
                f"使用者問題：{query_text}\n\n"
                f"即時資料：\n{realtime_info}"
            ),
        },
    ]
    reply = query_gemini(messages)
    return clean_markdown_for_line(reply)
