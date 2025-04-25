# app/main.py
import os
from dotenv import load_dotenv
load_dotenv()

from fastapi import FastAPI, Request, Header, HTTPException
from linebot import WebhookHandler
import asyncio
from app.line_bot import handle_events
from app.memory import init_db
from app.earthquake import earthquake_checker
from app.schedule_notification import start_notifications_scheduler  # ✅ 加入這行

app = FastAPI()
handler = WebhookHandler(os.getenv("LINE_CHANNEL_SECRET"))
init_db()

@app.on_event("startup")
async def startup_event():
    asyncio.create_task(earthquake_checker(interval=30, min_magnitude=4.0))
    asyncio.create_task(start_notifications_scheduler())

@app.post("/callback")
async def callback(request: Request, x_line_signature: str = Header(None)):
    body = await request.body()
    try:
        handler.handle(body.decode("utf-8"), x_line_signature)
    except Exception as e:
        print(f"❌ 錯誤：{e}")
        raise HTTPException(status_code=400, detail=str(e))
    return "OK"

handle_events(handler)