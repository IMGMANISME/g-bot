#app/gemini_engine.py
import os
import re
import google.generativeai as genai
from tenacity import retry, stop_after_attempt, wait_exponential
from app.config import config
from app.utils.logger import setup_logger
from app.utils.decorators import handle_exceptions

logger = setup_logger("gemini_engine")


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

    # 1) 最優先：如果有明確 <reply>/<answer> 標籤，只取最後一組標籤內容
    tagged_replies = re.findall(
        r"<(reply|answer)>\s*(.*?)\s*</\1>",
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
        r"(?m)^[ \t]*[•\-*]?[ \t]*(User|Role|Bosses|Instruction|Constraints|Bot Identity|Superiors|Persona|Current User|Previous interaction|Maintain the persona|Confirm identity|Language|Constraint check|Check|Draft \d|Drafts?|Traditional Chinese|Taiwan|Concise|Natural human tone|No emojis|No robotic|No hallucinations|Thought process):.*$",
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
        r"Format|Language|No emojis|Wrap in|Natural tone|Wait,)\b"
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

# === 初始化 Gemini 模型 ===
genai.configure(api_key=config.GEMINI_API_KEY)

model_gemini = genai.GenerativeModel(
    model_name=config.GEMINI_MODEL,
    generation_config={
        "temperature": config.GEMINI_TEMPERATURE,
        "top_p": 1,
        "top_k": 40,
        "max_output_tokens": config.GEMINI_MAX_TOKENS,
    },
    safety_settings=[
        {"category": "HARM_CATEGORY_HARASSMENT", "threshold": "BLOCK_NONE"},
        {"category": "HARM_CATEGORY_HATE_SPEECH", "threshold": "BLOCK_NONE"},
        {"category": "HARM_CATEGORY_SEXUALLY_EXPLICIT", "threshold": "BLOCK_NONE"},
        {"category": "HARM_CATEGORY_DANGEROUS_CONTENT", "threshold": "BLOCK_NONE"},
    ]
)

def _format_messages_for_gemini(messages: list) -> list:
    """將訊息格式化為 Gemini SDK 要求的格式"""
    formatted = []
    for m in messages:
        role = "user" if m["role"] in ["user", "system", "realtime_info"] else "model"
        # 其實 system 在這裡應該由 system_instruction 處理，但如果歷史中有，我們先轉為 user
        formatted.append({
            "role": role,
            "parts": [m["content"]]
        })
    return formatted

@retry(
    stop=stop_after_attempt(3), 
    wait=wait_exponential(multiplier=1, min=2, max=10),
    reraise=True
)
@handle_exceptions("我現在懶得回答你，請等一下再試😉", log_error=True)
def query_gemini(messages: list) -> str:
    """查詢 Gemini AI 模型"""
    if not messages:
        logger.warning("收到空的訊息列表")
        return "⚠️ 沒有訊息內容"
    
    # 1. 提取系統指令 (System Instruction)
    system_parts = []
    other_messages = []
    for m in messages:
        if m["role"] == "system":
            system_parts.append(m["content"])
        else:
            other_messages.append(m)
    
    system_instruction = "\n".join(system_parts) if system_parts else None

    # 2. 處理摘要邏輯（如果對話過長）
    max_history_len = 10  # 超過 10 則訊息考慮摘要
    if len(other_messages) > max_history_len:
        logger.info(f"對話紀錄過長 ({len(other_messages)}), 考慮執行摘要...")
        # 這裡保留原有的摘要邏輯概念，但改進實作
        # 暫時簡化：只取最後 10 則訊息
        other_messages = other_messages[-10:]

    # 3. 建立模型實例 (包含系統指令)
    dynamic_model = genai.GenerativeModel(
        model_name=config.GEMINI_MODEL,
        generation_config={
            "temperature": config.GEMINI_TEMPERATURE,
            "top_p": 1,
            "top_k": 40,
            "max_output_tokens": config.GEMINI_MAX_TOKENS,
        },
        system_instruction=system_instruction,
        safety_settings=[
            {"category": "HARM_CATEGORY_HARASSMENT", "threshold": "BLOCK_NONE"},
            {"category": "HARM_CATEGORY_HATE_SPEECH", "threshold": "BLOCK_NONE"},
            {"category": "HARM_CATEGORY_SEXUALLY_EXPLICIT", "threshold": "BLOCK_NONE"},
            {"category": "HARM_CATEGORY_DANGEROUS_CONTENT", "threshold": "BLOCK_NONE"},
        ]
    )

    # 4. 格式化剩餘訊息
    formatted_messages = _format_messages_for_gemini(other_messages)
    
    try:
        # 使用 generate_content 傳入完整歷史
        response = dynamic_model.generate_content(formatted_messages)

        if hasattr(response, "text") and response.text:
            result = _extract_final_reply(response.text)

            # 若抽取後變空字串，回退原文以避免空回覆
            if not result:
                result = response.text.strip()

            logger.info(f"Gemini 回覆處理成功，最終長度: {len(result)} 字元")
            return result
        else:
            logger.warning("Gemini 沒有回應內容")
            return "⚠️ Gemini 沒有回應內容，請稍後再試。"

    except Exception as e:
        logger.error(f"Gemini API 發生錯誤: {e}")
        raise

def validate_gemini_config():
    """驗證 Gemini 配置"""
    if not config.GEMINI_API_KEY:
        raise ValueError("GEMINI_API_KEY 未設定")
    
    try:
        # 測試 API 連接
        test_response = model_gemini.generate_content("Hello")
        logger.info("✅ Gemini API 連接測試成功")
        return True
    except Exception as e:
        logger.error(f"❌ Gemini API 連接測試失敗: {e}")
        return False

if __name__ == "__main__":
    validate_gemini_config()
