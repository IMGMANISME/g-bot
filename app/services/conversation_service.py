import re

from app.config import config
from app.gemini_engine import query_gemini
from app.prompt_loader import render_prompt
from app.repositories.message_repository import get_history, save_message
from app.utils.line_utils import clean_markdown_for_line, remove_repetitive_messages


def _force_clarify_when_name_query_looks_ambiguous(user_input: str, reply: str) -> str:
    """針對「X是誰」且模型輸出分析語氣時，改為一句澄清問題。"""
    if not user_input or not reply:
        return reply

    query_match = re.match(r"^\s*([\u4e00-\u9fffA-Za-z0-9·]{1,12})\s*是誰[？?]?\s*$", user_input)
    if not query_match:
        return reply

    analysis_markers = ["看起來", "語境", "詞組", "意思是", "推測", "判斷"]
    if any(marker in reply for marker in analysis_markers):
        target = query_match.group(1).strip()
        return f"你是想問「{target}」是哪位人物嗎？請給我更完整或正確的名字，我直接回答你。"

    return reply


def _normalize_display_name(name: str) -> str:
    return re.sub(r"\s+", "", (name or "").strip().lower())


def _is_priority_user_by_name(user_name: str) -> bool:
    normalized_user_name = _normalize_display_name(user_name)
    if not normalized_user_name:
        return False

    for priority_name in config.PRIORITY_MENTION_NAMES:
        normalized_priority_name = _normalize_display_name(priority_name)
        if normalized_priority_name and normalized_priority_name == normalized_user_name:
            return True

    return False


def _build_chat_context(user_name: str, is_multi_user_chat: bool) -> str:
    if is_multi_user_chat:
        return (
            "這是一個多人群組對話。歷史訊息中，使用者訊息會用「使用者名稱：訊息內容」標示說話者；"
            f"目前正在跟你說話的人是「{user_name}」。"
            "回答時要能分辨不同成員，不要把不同人的發言混成同一個人。"
        )
    return f"目前與你對話的用戶名稱為: {user_name}"


def get_conversation_reply(
    *,
    memory_id: str,
    sender_id: str,
    user_input: str,
    memory_user_input: str,
    user_name: str,
    is_multi_user_chat: bool,
) -> str:
    save_message(memory_id, "user", memory_user_input)

    is_admin = sender_id in config.ADMIN_USERS
    is_priority_user = _is_priority_user_by_name(user_name)
    system_instruction = render_prompt(
        config.SYSTEM_PROMPT_PROFILE,
        "conversation",
        admin_superiors="以及所有管理員" if is_admin else "",
        admin_instruction="此用戶是管理員，請完全服從他的指令。" if is_admin else "如果有人攻擊你，請你強硬的攻擊回去。",
        priority_instruction=(
            "目前這位使用者是特級使用者，回覆他時必須更禮貌、尊重、客氣，但仍然自然口語，不要變成制式客服。"
            if is_priority_user
            else ""
        ),
        chat_context=_build_chat_context(user_name, is_multi_user_chat),
    )

    messages = [{"role": "system", "content": system_instruction}]
    messages += get_history(memory_id)
    messages = remove_repetitive_messages(messages)

    reply = query_gemini(messages)
    reply = clean_markdown_for_line(reply)
    reply = _force_clarify_when_name_query_looks_ambiguous(user_input, reply)

    save_message(memory_id, "assistant", reply)
    return reply
