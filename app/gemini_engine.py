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
    
    # 將 messages 轉成純文字，動態判斷是否需要摘要
    content_list = []
    for msg in messages:
        content_list.append(f"{msg['role']}: {msg['content']}")
        
    full_prompt = "\n".join(content_list)
    max_length = 6000
    
    if len(full_prompt) > max_length and len(messages) > 3:
        logger.info("對話紀錄超過閾值，啟動智能摘要機制...")
        # 保留 System 提示設定
        sys_msg = messages[0]['content']
        
        # 取前面的 60% 歷史訊息進行摘要，保留最新的 40%
        split_idx = int(len(messages) * 0.6)
        if split_idx == 0: split_idx = 1
        
        old_msgs = messages[1:split_idx]
        recent_msgs = messages[split_idx:]
        
        old_text = "\n".join([f"{m['role']}: {m['content']}" for m in old_msgs])
        summary_prompt = f"請將以下對話總結成精簡的上下文要點，務必保留關鍵資訊、話題與使用者偏好:\n\n{old_text}"
        
        try:
            summary_res = model_gemini.generate_content(summary_prompt)
            summary_text = summary_res.text.strip() if hasattr(summary_res, "text") and summary_res.text else ""
            logger.info("成功建立歷史摘要")
        except Exception as e:
            logger.warning(f"摘要生成失敗: {e}")
            summary_text = ""
            
        if summary_text:
            sys_msg += f"\n\n[系統：請參考以下歷史對話摘要以了解脈絡]\n{summary_text}"
            
        prompt_parts = [f"system: {sys_msg}"]
        for m in recent_msgs:
            prompt_parts.append(f"{m['role']}: {m['content']}")
            
        prompt = "\n".join(prompt_parts)
    else:
        prompt = full_prompt
    
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