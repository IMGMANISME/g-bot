#app/gemini_engine.py
import os
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

# === Gemini 查詢（將 chat history 串成文字）===
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
    
    # 將 messages 轉成純文字，限制長度避免超過 token 限制
    prompt_parts = []
    total_length = 0
    max_length = 8000  # 保守估計，避免超過模型限制
    
    for msg in reversed(messages):  # 從最新的訊息開始
        content = f"{msg['role']}: {msg['content']}"
        if total_length + len(content) > max_length:
            break
        prompt_parts.insert(0, content)
        total_length += len(content)
    
    prompt = "\n".join(prompt_parts)
    
    logger.debug(f"發送給 Gemini 的 prompt 長度: {len(prompt)} 字元")

    try:
        response = model_gemini.generate_content(prompt)

        if hasattr(response, "text") and response.text:
            result = response.text.strip()
            logger.info(f"Gemini 回覆長度: {len(result)} 字元")
            return result
        else:
            logger.warning("Gemini 沒有回應內容")
            return "⚠️ Gemini 沒有回應內容，請稍後再試。"

    except Exception as e:
        logger.error(f"Gemini API 發生錯誤: {e}")
        raise  # 讓 retry 裝飾器處理重試

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