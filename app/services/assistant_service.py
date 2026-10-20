# app/services/assistant_service.py
"""一般訊息的處理流程：聊天，或透過工具查天氣、設提醒、找餐廳。

1. 說法明確時由規則直接決定工具（tools/rules.py），否則由模型決定要聊天還是用工具。
2. 執行工具後，把結果交給模型用人設口吻改寫；改寫失敗就用工具提供的模板。
"""
import re
from dataclasses import dataclass, field
from datetime import datetime

from google.genai import types

from app.config import config
from app.gemini_engine import GeminiUnavailable, plan_reply, reply_with_tool_result
from app.prompt_loader import render_prompt
from app.repositories.message_repository import get_history, save_message
from app.tools.base import QuickReplyItem, ToolContext, execute_tool, gemini_tools, should_rewrite
from app.tools.rules import match_fast_path
from app.utils.line_utils import clean_markdown_for_line, remove_repetitive_messages
from app.utils.logger import setup_logger
from app.utils.time_utils import WEEKDAY_NAMES, now_taipei

logger = setup_logger("assistant_service")


@dataclass
class AssistantReply:
    text: str
    quick_replies: list[QuickReplyItem] = field(default_factory=list)


def _force_clarify_when_name_query_looks_ambiguous(user_input: str, reply: str) -> str:
    """針對「X是誰」且模型輸出分析語氣時，改為一句澄清問題。"""
    if not user_input or not reply:
        return reply

    query_match = re.match(r"^\s*([一-鿿A-Za-z0-9·]{1,12})\s*是誰[？?]?\s*$", user_input)
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


def _build_system_instruction(sender_id: str, user_name: str, is_multi_user_chat: bool, now: datetime) -> str:
    is_admin = sender_id in config.ADMIN_USERS
    is_priority_user = _is_priority_user_by_name(user_name)
    return render_prompt(
        config.SYSTEM_PROMPT_PROFILE,
        "conversation",
        admin_superiors="以及所有管理員" if is_admin else "",
        admin_instruction="此用戶是管理員，請完全服從他的指令。" if is_admin else "如果有人攻擊你，請你強硬的攻擊回去。",
        priority_instruction=(
            "目前這位使用者是特級使用者，回覆他時必須更禮貌、尊重、客氣，但仍然自然口語，不要變成制式客服。"
            if is_priority_user
            else ""
        ),
        current_time=f"{now:%Y-%m-%d %H:%M} 星期{WEEKDAY_NAMES[now.weekday()]}",
        chat_context=_build_chat_context(user_name, is_multi_user_chat),
    )


def get_assistant_reply(
    *,
    memory_id: str,
    chat_id: str,
    sender_id: str,
    user_input: str,
    memory_user_input: str,
    user_name: str,
    is_multi_user_chat: bool,
    mention_prefix: str = "",
) -> AssistantReply:
    now = now_taipei()
    save_message(memory_id, "user", memory_user_input)
    history = remove_repetitive_messages(get_history(memory_id))
    system_instruction = _build_system_instruction(sender_id, user_name, is_multi_user_chat, now)

    model_content = None
    fast_path = match_fast_path(user_input, now)
    if fast_path:
        name, args = fast_path
        logger.info(f"快速判斷使用工具: {name} {args}")
        function_call = types.FunctionCall(name=name, args=args)
    else:
        try:
            turn = plan_reply(system_instruction, history, gemini_tools())
        except GeminiUnavailable as e:
            # 錯誤訊息不存進對話紀錄，避免模型之後把它當成自己說過的話
            return AssistantReply(e.reply)

        if turn.text:
            reply = _force_clarify_when_name_query_looks_ambiguous(user_input, clean_markdown_for_line(turn.text))
            save_message(memory_id, "assistant", reply)
            return AssistantReply(reply)

        function_call, model_content = turn.function_call, turn.content
        name, args = function_call.name, dict(function_call.args or {})

    ctx = ToolContext(
        chat_id=chat_id,
        sender_id=sender_id,
        user_text=user_input,
        now=now,
        mention_prefix=mention_prefix,
    )
    result = execute_tool(name, args, ctx)

    rewritten = (
        reply_with_tool_result(system_instruction, history, gemini_tools(), function_call, result.data, model_content)
        if should_rewrite(name) else None
    )
    reply = clean_markdown_for_line(rewritten) if rewritten else result.fallback_text
    save_message(memory_id, "assistant", reply)

    if result.attachment:
        reply = f"{reply}\n\n{result.attachment}"
    return AssistantReply(reply, result.quick_replies)
