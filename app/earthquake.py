# app/earthquake.py
import requests
import os
from datetime import datetime, timedelta
from typing import Optional

from app.utils.line_utils import push_line_message_to_users
from app.config import config
from app.repositories.user_repository import get_earthquake_recipient_ids
from app.repositories.system_state_repository import (
    get_system_state,
    set_system_state,
    try_acquire_job_lock,
)
from app.utils.logger import setup_logger
from app.utils.decorators import handle_exceptions

logger = setup_logger("earthquake")
CWA_API_KEY = os.getenv("CWA_API_KEY")
LAST_EARTHQUAKE_ID_KEY = "earthquake:last_processed_id"


def normalize_earthquake_id(value) -> str:
    """Return a stable string ID for DB comparison and storage."""
    return str(value or "").strip()


def parse_earthquake_data(latest: dict) -> tuple[Optional[float], Optional[datetime], Optional[str]]:
    """解析地震資料"""
    try:
        magnitude = float(latest["EarthquakeInfo"]["EarthquakeMagnitude"]["MagnitudeValue"])
    except (ValueError, KeyError, TypeError):
        magnitude = None
    
    try:
        time_str = latest["EarthquakeInfo"]["OriginTime"]
        dt = datetime.strptime(time_str, "%Y-%m-%d %H:%M:%S")
    except (KeyError, ValueError, TypeError):
        dt = None
    
    try:
        location = latest["EarthquakeInfo"]["Epicenter"]["Location"]
    except (KeyError, TypeError):
        location = None
    
    return magnitude, dt, location

def is_recent_earthquake(earthquake_time: datetime, max_latency_seconds: int = 900) -> bool:
    """檢查地震是否為最近發生的"""
    if not earthquake_time:
        return False
    
    now = datetime.utcnow() + timedelta(hours=8)  # 台灣時間
    time_diff = abs((now - earthquake_time).total_seconds())
    return time_diff <= max_latency_seconds

def create_earthquake_message(magnitude: float, earthquake_time: datetime, location: str) -> str:
    """建立地震推播訊息"""
    return (
        f"🌍【地震速報】\n\n"
        f"📍 震央：{location}\n"
        f"⏰ 時間：{earthquake_time.strftime('%m/%d %H:%M')}\n"
        f"💥 規模：{magnitude}"
    )

@handle_exceptions("地震API請求失敗")
def fetch_earthquake_data() -> Optional[dict]:
    """取得地震資料"""
    if not CWA_API_KEY:
        logger.error("CWA_API_KEY 環境變數未設定")
        return None
    
    try:
        url = "https://opendata.cwa.gov.tw/api/v1/rest/datastore/E-A0015-001"
        params = {"Authorization": CWA_API_KEY}
        
        response = requests.get(url, params=params, timeout=10)
        response.raise_for_status()
        
        data = response.json()
        earthquakes = data.get("records", {}).get("Earthquake", [])
        
        if not earthquakes:
            logger.debug("目前沒有地震資料")
            return None
            
        return earthquakes[0]
        
    except requests.exceptions.Timeout:
        logger.warning("地震API請求超時")
        return None
    except requests.exceptions.RequestException as e:
        logger.error(f"地震API請求失敗: {e}")
        return None
    except Exception as e:
        logger.error(f"解析地震資料失敗: {e}")
        return None

def check_earthquake_job(min_magnitude: float = 4.0):
    """
    執行單次地震檢查作業
    """
    if not CWA_API_KEY:
        return

    try:
        if not try_acquire_job_lock("earthquake", ttl_seconds=max(10, config.EARTHQUAKE_CHECK_INTERVAL - 1)):
            return

        # 取得最新地震資料
        latest_earthquake = fetch_earthquake_data()
        if not latest_earthquake:
            return

        # 檢查是否為新地震
        eq_id = normalize_earthquake_id(latest_earthquake.get("EarthquakeNo"))
        if not eq_id:
            logger.warning("地震資料缺少 EarthquakeNo，跳過處理")
            return

        if eq_id == get_system_state(LAST_EARTHQUAKE_ID_KEY):
            return

        # 解析獨立的圖片 URL
        image_url = latest_earthquake.get("ReportImageURI")

        # 解析地震資料
        magnitude, earthquake_time, location = parse_earthquake_data(latest_earthquake)
        
        # 驗證資料完整性
        if not all([magnitude, earthquake_time, location]):
            logger.warning(f"地震資料不完整，跳過處理: EQ_ID={eq_id}")
            set_system_state(LAST_EARTHQUAKE_ID_KEY, eq_id)
            return

        # 檢查規模是否達到推播標準
        if magnitude < min_magnitude:
            logger.debug(f"地震規模 {magnitude} 未達推播標準 {min_magnitude}")
            set_system_state(LAST_EARTHQUAKE_ID_KEY, eq_id)
            return

        # 檢查是否為近期地震
        if not is_recent_earthquake(earthquake_time, config.EARTHQUAKE_MAX_LATENCY):
            logger.debug(f"地震時間過舊，不推播: {earthquake_time}")
            set_system_state(LAST_EARTHQUAKE_ID_KEY, eq_id)
            return

        # 更新最後處理的地震ID
        set_system_state(LAST_EARTHQUAKE_ID_KEY, eq_id)

        # 建立推播訊息
        message = create_earthquake_message(magnitude, earthquake_time, location)
        
        # 取得符合訂閱與門檻設定的聊天室列表並推播
        user_ids = get_earthquake_recipient_ids(magnitude, min_magnitude)
        if user_ids:
            logger.info(f"🚨 地震推播: 規模 {magnitude}，推送給 {len(user_ids)} 位用戶")
            push_line_message_to_users(message, user_ids, image_url=image_url)
        else:
            logger.warning("沒有用戶可推播地震訊息")

    except Exception as e:
        logger.error(f"地震監控發生錯誤: {e}")

def setup_earthquake_job(scheduler, interval: int = 20, min_magnitude: float = 4.0):
    """註冊地震排程任務至 APScheduler"""
    if not CWA_API_KEY:
        logger.error("❌ CWA_API_KEY 未設定，地震監控無法啟動")
        return
        
    logger.info("✅ 註冊地震監控排程作業")
    logger.info(f"⏱️ 檢查間隔: {interval} 秒")
    logger.info(f"🌍 最小規模: {min_magnitude}")
    
    scheduler.add_job(
        check_earthquake_job,
        'interval',
        seconds=interval,
        kwargs={"min_magnitude": min_magnitude},
        id='earthquake_checker',
        replace_existing=True
    )

def validate_earthquake_config() -> bool:
    """驗證地震監控配置"""
    if not CWA_API_KEY:
        logger.error("❌ CWA_API_KEY 環境變數未設定")
        return False
    
    try:
        # 測試 API 連接
        url = "https://opendata.cwa.gov.tw/api/v1/rest/datastore/E-A0015-001"
        params = {"Authorization": CWA_API_KEY}
        response = requests.get(url, params=params, timeout=5)
        
        if response.status_code == 200:
            logger.info("✅ 地震API連接測試成功")
            return True
        else:
            logger.error(f"❌ 地震API連接測試失敗: {response.status_code}")
            return False
            
    except Exception as e:
        logger.error(f"❌ 地震API連接測試失敗: {e}")
        return False

# 在模組載入時驗證配置
if __name__ == "__main__":
    validate_earthquake_config()
