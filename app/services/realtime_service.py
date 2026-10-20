from app.config import config
from app.gemini_engine import query_gemini
from app.prompt_loader import render_prompt
from app.realtime_search import get_realtime_info
from app.repositories.message_repository import save_message
from app.utils.line_utils import clean_markdown_for_line


def get_realtime_reply(*, memory_id: str, user_input: str, memory_user_input: str) -> str:
    realtime_info = get_realtime_info(user_input)
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
                f"使用者問題：{user_input}\n\n"
                f"即時資料：\n{realtime_info}"
            ),
        },
    ]
    reply = query_gemini(messages)
    return clean_markdown_for_line(reply)
