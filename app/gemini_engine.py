#app/gemini_engine.py
import os
import google.generativeai as genai
from tenacity import retry, stop_after_attempt, wait_fixed
from app.realtime_search import needs_realtime_info, get_realtime_info

# === 初始化 Gemini 模型 ===
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
genai.configure(api_key=GEMINI_API_KEY)

model_gemini = genai.GenerativeModel(
    model_name="gemma-3-27b-it",  # ✅ 目前可用的正式模型名稱
    generation_config={
        "temperature": 0.7,
        "top_p": 1,
        "top_k": 40,
        "max_output_tokens": 2048,
    },
    safety_settings=[
        {"category": "HARM_CATEGORY_HARASSMENT", "threshold": "BLOCK_NONE"},
        {"category": "HARM_CATEGORY_HATE_SPEECH", "threshold": "BLOCK_NONE"},
        {"category": "HARM_CATEGORY_SEXUALLY_EXPLICIT", "threshold": "BLOCK_NONE"},
        {"category": "HARM_CATEGORY_DANGEROUS_CONTENT", "threshold": "BLOCK_NONE"},
    ]
)

# === Gemini 查詢（將 chat history 串成文字）===
@retry(stop=stop_after_attempt(3), wait=wait_fixed(2))
def query_gemini(messages: list) -> str:
    # 將 messages 轉成純文字
    prompt = "\n".join([f"{m['role']}: {m['content']}" for m in messages])

    try:
        response = model_gemini.generate_content(prompt)

        if hasattr(response, "text"):
            result = response.text.strip()
            return result
        else:
            return "⚠️ Gemini 沒有回應內容，請稍後再試。"

    except Exception as e:
        print(f"❌ Gemini 發生錯誤：{e}")
        return f"我現在懶得回答你，請等一下再試😉"