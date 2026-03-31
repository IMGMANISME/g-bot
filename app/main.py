# app/main.py
import os
import asyncio
from contextlib import asynccontextmanager
from dotenv import load_dotenv

# 載入環境變數
load_dotenv()

from fastapi import FastAPI, Request, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from linebot import WebhookHandler
from linebot.exceptions import InvalidSignatureError

from app.line_bot import handle_events
from app.database import init_db
from app.earthquake import setup_earthquake_job
from app.schedule_notification import start_scheduler
from app.config import config, validate_config
from app.utils.logger import setup_logger
from app.gemini_engine import validate_gemini_config
from app.utils.performance import performance_monitor

logger = setup_logger("main")

@asynccontextmanager
async def lifespan(app: FastAPI):
    """應用程式生命週期管理"""
    # 啟動時執行
    logger.info("🚀 G-Bot 啟動中...")
    
    try:
        # 驗證配置
        validate_config()
        logger.info("✅ 配置驗證通過")
        
        # 驗證 Gemini 連接
        if validate_gemini_config():
            logger.info("✅ Gemini API 連接正常")
        
        # 初始化資料庫
        init_db()
        logger.info("✅ 資料庫初始化完成")
        
        # 註冊地震監控任務至排程器
        from app.schedule_notification import scheduler
        setup_earthquake_job(
            scheduler,
            interval=config.EARTHQUAKE_CHECK_INTERVAL, 
            min_magnitude=config.EARTHQUAKE_MIN_MAGNITUDE
        )
        logger.info("✅ 地震監控任務已註冊")
        
        # 啟動所有排程任務
        start_scheduler()
        logger.info("✅ 背景排程器已啟動 (含通知與地震)")
        
        logger.info("🎉 G-Bot 啟動完成！")
        
    except Exception as e:
        logger.error(f"❌ 啟動失敗: {e}")
        raise
    
    yield
    
    # 關閉時執行
    logger.info("🛑 G-Bot 正在關閉...")

app = FastAPI(
    title="G-Bot",
    description="智能 LINE 聊天機器人",
    version="2.0.0",
    lifespan=lifespan
)

# 添加 CORS 中介軟體
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

handler = WebhookHandler(config.LINE_CHANNEL_SECRET)

@app.get("/")
async def root():
    """健康檢查端點"""
    return {
        "status": "healthy",
        "service": "G-Bot",
        "version": "2.0.0"
    }

@app.get("/health")
async def health_check():
    """詳細的健康檢查"""
    try:
        # 檢查資料庫連接
        from app.database import SessionLocal
        with SessionLocal() as session:
            session.execute("SELECT 1")
        
        return {
            "status": "healthy",
            "database": "connected",
            "gemini": "configured" if config.GEMINI_API_KEY else "missing",
            "line": "configured" if config.LINE_CHANNEL_ACCESS_TOKEN else "missing"
        }
    except Exception as e:
        logger.error(f"健康檢查失敗: {e}")
        raise HTTPException(status_code=503, detail="Service unhealthy")

@app.get("/metrics")
async def get_metrics():
    """取得效能指標"""
    return performance_monitor.get_performance_report()

@app.post("/callback")
async def callback(request: Request, x_line_signature: str = Header(None)):
    """LINE Bot webhook 回調端點"""
    body = await request.body()
    
    # 記錄請求
    logger.debug(f"收到 webhook 請求，簽名: {x_line_signature}")
    
    try:
        handler.handle(body.decode("utf-8"), x_line_signature)
        logger.debug("Webhook 處理成功")
        return "OK"
    except InvalidSignatureError:
        logger.error("❌ LINE webhook 簽名驗證失敗")
        raise HTTPException(status_code=400, detail="Invalid signature")
    except Exception as e:
        logger.error(f"❌ Webhook 處理失敗：{e}")
        raise HTTPException(status_code=500, detail=str(e))

# 註冊事件處理器
handle_events(handler)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=int(os.getenv("PORT", 8787)),
        reload=True,
        log_level="info"
    )