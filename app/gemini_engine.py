#app/gemini_engine.py
import re
from dataclasses import dataclass
from google import genai
from google.genai import errors, types
from tenacity import retry, retry_if_exception, stop_after_attempt, wait_exponential
from app.config import config
from app.utils.logger import setup_logger

logger = setup_logger("gemini_engine")


META_LEAK_PATTERNS = [
    r"\bConstraint\s*:",
    r"\bConstraints?\s*:",
    r"\bConstraint check\b",
    r"\bThe system prompt\b",
    r"\bThe user prompt\b",
    r"\bWrapped in\b",
    r"\bNo hallucinations\b",
    r"\bNo analysis/process\b",
    r"\bNatural human tone\b",
    r"\bThought process\b",
    r"\bDrafting Response\b",
    r"\bFinal Plan\b",
    r"<(thought|reasoning|draft|details|planning|think|thinking)>",
    r"<\|[^>]+?\|>",
]


def _contains_meta_leak(text: str) -> bool:
    """判斷模型輸出是否包含不該給使用者看的規則檢查或推理痕跡。"""
    if not text:
        return False
    return any(re.search(pattern, text, flags=re.IGNORECASE) for pattern in META_LEAK_PATTERNS)


def _clean_reply_payload(text: str) -> str:
    """清理 reply 內容中的包裝符號與殘留標記。"""
    cleaned = (text or "").strip()
    cleaned = cleaned.strip("`\"'“”")
    cleaned = re.sub(r"^<(reply|answer)>\s*", "", cleaned, flags=re.IGNORECASE).strip()
    cleaned = re.sub(r"\s*</(reply|answer)>$", "", cleaned, flags=re.IGNORECASE).strip()
    cleaned = cleaned.strip("`\"'“”")
    return cleaned.strip()


def _extract_final_reply(raw_text: str) -> str:
    """從模型原始輸出提取最終可回覆內容，盡量排除 thought/reasoning 片段。"""
    if not raw_text:
        return ""

    result = raw_text.strip()

    # 1) 最優先：如果有明確 <reply>/<answer> 標籤，只取最後一組標籤內容。
    # 避免把「Wrapped in `<reply>` tags?」這種檢查清單中的假標籤當成起點。
    tagged_replies = re.findall(
        r"<(reply|answer)>\s*((?:(?!<(?:reply|answer)>|</\1>).)*?)\s*</\1>",
        result,
        flags=re.IGNORECASE | re.DOTALL,
    )
    if tagged_replies:
        return _clean_reply_payload(tagged_replies[-1][1])

    # 1.1) 常見於 Gemma：只出現 <reply> 開頭但沒關閉標籤
    if re.search(r"<(reply|answer)>", result, flags=re.IGNORECASE):
        split_by_open_tag = re.split(r"<(reply|answer)>", result, flags=re.IGNORECASE)
        if len(split_by_open_tag) >= 3:
            # re.split 會保留群組，真正內容在最後一段
            tail = split_by_open_tag[-1]
            tail = re.split(r"</(reply|answer)>", tail, flags=re.IGNORECASE)[0]
            cleaned_tail = _clean_reply_payload(tail)
            if cleaned_tail:
                return cleaned_tail

    # 1.2) 常見於規劃輸出：Format: `<reply>...`
    format_reply = re.search(
        r"(?:Format|格式)\s*:\s*`?\s*<(?:reply|answer)>\s*(.*?)\s*(?:</(?:reply|answer)>)?`?\s*$",
        result,
        flags=re.IGNORECASE | re.DOTALL,
    )
    if format_reply:
        cleaned_format = _clean_reply_payload(format_reply.group(1))
        if cleaned_format:
            return cleaned_format

    # 2) 嘗試移除常見 thought channel 區塊
    channel_patterns = [
        r"<\|channel\>\s*thought.*?<channel\|>",
        r"<\|channel\|>\s*thought.*?<\|channel\|>",
        r"<\|start\|>\s*assistant\s*to=thought.*?<\|end\|>",
        r"<(thought|reasoning|draft|details|planning|think|thinking)>.*?</\1>",
        r"```(thought|think|thinking|reasoning)\n.*?```",
    ]
    for pattern in channel_patterns:
        result = re.sub(pattern, "", result, flags=re.IGNORECASE | re.DOTALL).strip()

    # 3) 如果有 "Final Response" 類標記，優先取後半段
    final_markers = ["Final Response", "final response", "最終回答", "最終回覆"]
    for marker in final_markers:
        if marker in result:
            result = result.split(marker)[-1].strip(": \n")
            break

    # 4) 移除殘留 channel/token 控制字串
    result = re.sub(r"<\|[^>]+?\|>", "", result).strip()
    result = re.sub(r"<[^>\n]*?\|>", "", result).strip()

    # 5) 移除常見 checklist 推理行
    result = re.sub(
        r"(?m)^[ \t]*[•\-*]?[ \t]*(User|Role|Bosses|Instruction|Constraints?|Bot Identity|Superiors|Persona|Current User|Previous interaction|Maintain the persona|Confirm identity|Language|Constraint check|Check|Draft \d|Drafts?|Traditional Chinese|Taiwan|Concise|Natural human tone|No emojis|No robotic|No hallucinations|No analysis/process|Wrapped in|Thought process):.*$",
        "",
        result,
        flags=re.IGNORECASE,
    ).strip()
    result = re.sub(
        r"(?m)^.*(\?|:)\s*(Yes|No|None|Done|Check|Correct|Trad\.? Chinese)\.?\s*$",
        "",
        result,
        flags=re.IGNORECASE,
    ).strip()

    # 6) 過濾掉明顯的推理/規劃行，再挑最可能的最終句子
    meta_line_prefix = (
        r"^(The system prompt|The user prompt|Standard LLM behavior|Conflict Resolution|Decision|"
        r"Constraint Check|Drafting Response|Refining|Checking|Final Plan|Identity|Developer|"
        r"Format|Language|No emojis|Wrap in|Wrapped in|Natural tone|Wait,)\b"
    )
    lines = [line.strip() for line in result.splitlines() if line.strip()]
    filtered_lines = [
        line for line in lines
        if not re.match(meta_line_prefix, line, flags=re.IGNORECASE)
    ]

    # 優先取含中文且非 meta 的最後一行
    chinese_lines = [
        line for line in filtered_lines
        if re.search(r"[\u4e00-\u9fff]", line) and not re.search(r"(Plan|Constraint|Instruction)", line, re.I)
    ]
    if chinese_lines:
        return _clean_reply_payload(chinese_lines[-1])

    if filtered_lines:
        return _clean_reply_payload(filtered_lines[-1])

    # 7) 最後備援：若仍是多段，取最後一段
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", result) if p.strip()]
    if paragraphs:
        result = paragraphs[-1]

    return _clean_reply_payload(result)

# 金鑰無效、停權或沒有權限時，重試也不會成功
_AUTH_ERROR_CODES = (401, 403)
AUTH_ERROR_REPLY = "⚠️ 我的 AI 服務暫時無法使用，請稍後再試或聯絡管理員。"
QUOTA_ERROR_REPLY = "⚠️ 我今天講太多話了，AI 額度暫時用完，請稍後再試。"
GENERIC_ERROR_REPLY = "⚠️ 我現在有點忙不過來，請等一下再問我一次。"

PLAN_TIMEOUT_SECONDS = 45  # 判斷要聊天還是用工具
REWRITE_TIMEOUT_SECONDS = 25  # 把工具結果改寫成口語，超過就改用模板
MAX_HISTORY_MESSAGES = 10


class GeminiUnavailable(Exception):
    """模型呼叫失敗；reply 可以直接回覆給使用者。"""

    def __init__(self, reply: str):
        super().__init__(reply)
        self.reply = reply


@dataclass
class ModelTurn:
    """模型這一輪的回覆：一般文字，或要求呼叫工具。"""
    text: str | None = None
    function_call: types.FunctionCall | None = None
    content: types.Content | None = None  # 模型原始回覆，送回工具結果時要一起附上


def _is_auth_error(e: Exception) -> bool:
    return isinstance(e, errors.ClientError) and getattr(e, "code", None) in _AUTH_ERROR_CODES


def _is_retryable(e: BaseException) -> bool:
    """只重試伺服器錯誤與每分鐘上限；金鑰、額度、參數錯誤重試也沒用。"""
    if isinstance(e, errors.ServerError):
        return True
    return isinstance(e, errors.ClientError) and getattr(e, "code", None) == 429


def _to_unavailable(e: Exception) -> GeminiUnavailable:
    code = getattr(e, "code", None)
    if _is_auth_error(e):
        logger.error(f"Gemma/Gemini API 認證失敗 ({code} {getattr(e, 'status', '')})，請檢查 GEMINI_API_KEY 是否有效或已被停權")
        return GeminiUnavailable(AUTH_ERROR_REPLY)
    if code in (402, 429):
        logger.error(f"Gemma/Gemini API 額度不足或超過上限: {e}")
        return GeminiUnavailable(QUOTA_ERROR_REPLY)
    logger.error(f"Gemma/Gemini API 發生錯誤: {e}")
    return GeminiUnavailable(GENERIC_ERROR_REPLY)


# === 初始化 Gemma/Gemini API Client ===
genai_client = genai.Client(api_key=config.GEMINI_API_KEY)


def _format_messages_for_gemini(messages: list) -> list:
    """將 user/assistant 訊息轉成 Content；連續同角色的訊息合併成一則。"""
    formatted: list[types.Content] = []
    for m in messages[-MAX_HISTORY_MESSAGES:]:
        if m["role"] not in ("user", "assistant") or not m.get("content"):
            continue
        role = "model" if m["role"] == "assistant" else "user"
        if formatted and formatted[-1].role == role:
            formatted[-1].parts.append(types.Part.from_text(text=m["content"]))
        else:
            formatted.append(types.Content(role=role, parts=[types.Part.from_text(text=m["content"])]))
    return formatted


def _build_generation_config(
    system_instruction: str | None,
    tools: list[types.Tool] | None = None,
    timeout_seconds: int | None = None,
) -> types.GenerateContentConfig:
    return types.GenerateContentConfig(
        system_instruction=system_instruction,
        temperature=config.GEMINI_TEMPERATURE,
        top_p=1,
        top_k=40,
        max_output_tokens=config.GEMINI_MAX_TOKENS,
        tools=tools,
        # 工具由我們自己執行，不讓 SDK 自動呼叫
        automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True) if tools else None,
        http_options=types.HttpOptions(timeout=timeout_seconds * 1000) if timeout_seconds else None,
    )


@retry(
    retry=retry_if_exception(_is_retryable),
    stop=stop_after_attempt(2),
    wait=wait_exponential(multiplier=1, min=2, max=6),
    reraise=True,
)
def _generate(contents: list[types.Content], generation_config: types.GenerateContentConfig):
    return genai_client.models.generate_content(
        model=config.GEMINI_MODEL,
        contents=contents,
        config=generation_config,
    )


def _clean_text(response) -> str | None:
    """取出模型的文字回覆並清掉推理殘留；不適合直接送出時回傳 None。"""
    raw_text = getattr(response, "text", None)
    if not raw_text:
        candidates = getattr(response, "candidates", None) or []
        finish_reason = getattr(candidates[0], "finish_reason", None) if candidates else None
        logger.warning(f"Gemma/Gemini API 沒有回應內容，finish_reason: {finish_reason}")
        return None

    result = _extract_final_reply(raw_text)
    if not result:
        logger.warning("Gemma/Gemini API 回覆抽取後為空")
        return None
    if _contains_meta_leak(result):
        logger.warning("Gemma/Gemini API 回覆包含 meta leakage，拒絕送出")
        return None
    return result


def plan_reply(system_instruction: str, messages: list, tools: list[types.Tool]) -> ModelTurn:
    """讓模型決定直接回覆，或是呼叫哪個工具。失敗時丟出 GeminiUnavailable。"""
    contents = _format_messages_for_gemini(messages)
    if not contents:
        raise GeminiUnavailable("⚠️ 沒有訊息內容")

    try:
        response = _generate(contents, _build_generation_config(system_instruction, tools, PLAN_TIMEOUT_SECONDS))
    except Exception as e:
        raise _to_unavailable(e)

    function_calls = response.function_calls or []
    if function_calls:
        call = function_calls[0]
        logger.info(f"模型要求呼叫工具: {call.name} {dict(call.args or {})}")
        content = response.candidates[0].content if response.candidates else None
        return ModelTurn(function_call=call, content=content)

    text = _clean_text(response)
    if not text:
        raise GeminiUnavailable("我剛剛整理回覆時出錯了，請再問我一次。")
    logger.info(f"Gemma/Gemini API 回覆處理成功，最終長度: {len(text)} 字元")
    return ModelTurn(text=text)


def reply_with_tool_result(
    system_instruction: str,
    messages: list,
    tools: list[types.Tool],
    function_call: types.FunctionCall,
    result: dict,
    model_content: types.Content | None = None,
) -> str | None:
    """把工具結果交給模型改寫成口語回覆；失敗或逾時回傳 None，由呼叫端改用模板。"""
    contents = _format_messages_for_gemini(messages)
    contents.append(model_content or types.Content(role="model", parts=[types.Part(function_call=function_call)]))
    contents.append(types.Content(
        role="user",
        parts=[types.Part.from_function_response(name=function_call.name, response=result)],
    ))

    try:
        response = _generate(contents, _build_generation_config(system_instruction, tools, REWRITE_TIMEOUT_SECONDS))
    except Exception as e:
        logger.warning(f"工具結果改寫失敗，改用模板回覆: {e}")
        return None

    if response.function_calls:
        logger.warning("改寫時模型又要求呼叫工具，改用模板回覆")
        return None
    return _clean_text(response)


def validate_gemini_config():
    """驗證 Gemini 配置"""
    if not config.GEMINI_API_KEY:
        raise ValueError("GEMINI_API_KEY 未設定")
    
    try:
        # 測試 API 連接
        genai_client.models.generate_content(
            model=config.GEMINI_MODEL,
            contents="Hello",
            config=_build_generation_config(None),
        )
        logger.info("✅ Gemma/Gemini API 連接測試成功")
        return True
    except Exception as e:
        logger.error(f"❌ Gemma/Gemini API 連接測試失敗: {e}")
        return False

if __name__ == "__main__":
    validate_gemini_config()
