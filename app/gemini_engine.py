#app/gemini_engine.py
import os
import re
import google.generativeai as genai
from tenacity import retry, stop_after_attempt, wait_exponential
from app.config import config
from app.utils.logger import setup_logger
from app.utils.decorators import handle_exceptions

logger = setup_logger("gemini_engine")


def _extract_final_reply(raw_text: str) -> str:
    """從模型原始輸出提取最終可回覆內容，盡量排除 thought/reasoning 片段。"""
    if not raw_text:
        return ""

    result = raw_text.strip()

    # 1) 最優先：如果有明確 <reply>/<answer> 標籤，只取標籤內容
    tagged_reply = re.search(
        r"<(reply|answer)>\s*(.*?)\s*</\1>",
        result,
        flags=re.IGNORECASE | re.DOTALL,
    )
    if tagged_reply:
        return tagged_reply.group(2).strip()

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

    # 6) 若仍是多段，且前段像規則/推理，保留最後一段
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", result) if p.strip()]
    if len(paragraphs) > 1:
        last_p = paragraphs[-1]
        if not re.search(r"(Constraints|Instruction|User asks|Thought|Reasoning)", last_p, re.I):
            result = last_p

    return result.strip()

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
