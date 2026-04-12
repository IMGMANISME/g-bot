#app/gemini_engine.py
import os
import re
import google.generativeai as genai
from tenacity import retry, stop_after_attempt, wait_exponential
from app.config import config
from app.utils.logger import setup_logger
from app.utils.decorators import handle_exceptions

logger = setup_logger("gemini_engine")

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
            result = response.text.strip()
            
            # === 0. Gemma 4 原生思考 channel token 過濾 ===
            # Gemma 4 使用 <|channel>thought ... <channel|> 格式輸出思考過程
            # 最終回答在 <channel|> 之後
            channel_match = re.search(r'<\|channel\>thought.*?<channel\|>\s*(.*)', result, flags=re.DOTALL)
            if channel_match:
                result = channel_match.group(1).strip()
                logger.info("已過濾 Gemma 4 channel thinking 區塊")
            
            # === 1. 優先嘗試提取包裹在 <reply> 或 <answer> 標籤中的內容 ===
            reply_match = re.search(r'<(reply|answer)>(.*?)</\1>', result, flags=re.IGNORECASE | re.DOTALL)
            if reply_match:
                result = reply_match.group(2).strip()
            else:
                # === 2. 如果沒有標籤，執行積極的清道夫邏輯 ===
                # 移除常見的思考/計畫標籤內容
                result = re.sub(r'<(thought|reasoning|draft|details|planning|think|thinking)>.*?</\1>', '', result, flags=re.IGNORECASE | re.DOTALL).strip()
                
                # 移除 markdown 格式的思考區塊
                result = re.sub(r'```(thought|think|thinking|reasoning)\n.*?```', '', result, flags=re.IGNORECASE | re.DOTALL).strip()
                
                # 移除列表式推理 (User:, Role:, Instruction:, Constraints:, Check:, Yes/No 等)
                # 這是針對 Gemma 4 特別堅持輸出的那種「檢查表」
                result = re.sub(r'(?m)^[ \t]*[•\-*]?[ \t]*(User|Role|Bosses|Instruction|Constraints|Bot Identity|Superiors|Persona|Current User|Previous interaction|Maintain the persona|Confirm identity|Language|Constraint check|Check|Draft \d|Drafts?|Traditional Chinese|Taiwan|Concise|Natural human tone|No emojis|No robotic|No hallucinations|Thought process):.*$', '', result, flags=re.IGNORECASE).strip()
                
                # 處理那種最後一行的「自我檢查」模式 (例如: Concise? Yes. Emojis? None.)
                result = re.sub(r'(?m)^.*(\?|:)\s*(Yes|No|None|Done|Check|Correct|Trad\.? Chinese)\.?\s*$', '', result, flags=re.IGNORECASE).strip()

                # 移除 Final Response 之前的內容
                if "Final Response" in result:
                    result = result.split("Final Response")[-1].strip(": \n")
                
                # === 3. 備援邏輯：如果依然很長且看起來像推理，嘗試取最後一段 ===
                # 如果內容超過 3 段，且最後一段較短且不包含明顯的英文字樣，可能是最終答案
                paragraphs = [p.strip() for p in re.split(r'\n\s*\n', result) if p.strip()]
                if len(paragraphs) > 2:
                    last_p = paragraphs[-1]
                    # 如果最後一段沒有太多英文關鍵字，且前幾段包含關鍵字，則判定最後一段是答案
                    if not re.search(r'(Constraints|Instruction|User asks)', last_p, re.I):
                        result = last_p

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