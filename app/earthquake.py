# app/earthquake.py
import requests
import os
import asyncio
from datetime import datetime, timedelta

from app.line_bot import push_line_message_to_users
from app.memory import SessionLocal, UserState

CWA_API_KEY = os.getenv("CWA_API_KEY")
LAST_EARTHQUAKE_ID = None


async def earthquake_checker(interval: int = 30, min_magnitude: float = 5.0):
    """
    interval: 幾秒檢查一次
    min_magnitude: 達到此規模以上才推播
    """
    print("✅ Async Earthquake Checker started.")
    print(f"⏱️ Interval: {interval} seconds")
    print(f"🌍 Minimum Magnitude: {min_magnitude}")
    global LAST_EARTHQUAKE_ID

    while True:
        try:
            url = "https://opendata.cwa.gov.tw/api/v1/rest/datastore/E-A0015-001"
            params = {"Authorization": CWA_API_KEY}
            res = requests.get(url, params=params, timeout=10)
            data = res.json()

            earthquakes = data.get("records", {}).get("Earthquake", [])
            if not earthquakes:
                await asyncio.sleep(interval)
                continue

            latest = earthquakes[0]
            eq_id = latest.get("EarthquakeNo")

            if eq_id != LAST_EARTHQUAKE_ID:
                # 檢查地震規模是否符合
                try:
                    magnitude = float(latest["EarthquakeInfo"]["EarthquakeMagnitude"]["MagnitudeValue"])
                except (ValueError, KeyError):
                    magnitude = 0.0

                if magnitude >= min_magnitude:
                    # 解析地震時間
                    try:
                        time_str = latest["EarthquakeInfo"]["OriginTime"]
                        dt = datetime.strptime(time_str, "%Y-%m-%d %H:%M:%S")
                    except (KeyError, ValueError):
                        dt = None

                    # 只在地震時間與目前時間差值小於1分鐘內才推播
                    now = datetime.utcnow() + timedelta(hours=8)  # 台灣時間
                    if dt and abs((now - dt).total_seconds()) <= interval:
                        LAST_EARTHQUAKE_ID = eq_id

                        location = latest["EarthquakeInfo"]["Epicenter"]["Location"]

                        message = (
                            f"🌍【地震速報】\n\n"
                            f"📍 震央：{location}\n"
                            f"⏰ 時間：{dt.strftime('%m/%d %H:%M')}\n"
                            f"💥 規模：{magnitude}級"
                        )

                        db = SessionLocal()
                        try:
                            users = db.query(UserState).all()
                            user_ids = [u.sender_id for u in users]
                        finally:
                            db.close()

                        print(f"地震推播：{message}")
                        push_line_message_to_users(message, user_ids)

        except Exception as e:
            print(f"地震推播錯誤：{e}")

        await asyncio.sleep(interval)
