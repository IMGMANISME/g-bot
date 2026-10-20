"""測試共用設定：匯入 app 前先給假的環境變數，並擋掉所有真的網路呼叫。

資料庫測試需要真的 PostgreSQL，設定 TEST_DATABASE_URL 才會執行，否則自動略過。
"""
import os
from datetime import datetime

import pytest

TEST_DATABASE_URL = os.getenv("TEST_DATABASE_URL")

os.environ["DATABASE_URL"] = TEST_DATABASE_URL or "postgresql://test:test@localhost:5432/test"
os.environ.setdefault("LINE_CHANNEL_ACCESS_TOKEN", "test-line-token")
os.environ.setdefault("LINE_CHANNEL_SECRET", "test-line-secret")
os.environ.setdefault("GEMINI_API_KEY", "test-gemini-key")
os.environ.setdefault("CWA_API_KEY", "test-cwa-key")
os.environ.setdefault("GOOGLE_MAPS_API_KEY", "test-maps-key")
os.environ.setdefault("LOG_LEVEL", "CRITICAL")

from app.utils.time_utils import TAIPEI  # noqa: E402


@pytest.fixture(autouse=True)
def block_network(monkeypatch):
    """測試中任何沒被替換掉的網路呼叫都直接失敗，避免打到真的 API。"""
    import httpx
    import requests

    def blocked(*args, **kwargs):
        raise RuntimeError("測試中不允許真的網路呼叫，請替換掉這個外部服務")

    monkeypatch.setattr(requests.Session, "request", blocked)
    monkeypatch.setattr(httpx.Client, "send", blocked)


@pytest.fixture(autouse=True)
def clear_memory_cache():
    from app.utils.cache import global_cache
    global_cache.clear()
    yield
    global_cache.clear()


@pytest.fixture
def now():
    """固定的現在時間：2026-10-20（週二）14:30 台北時間"""
    return TAIPEI.localize(datetime(2026, 10, 20, 14, 30))


def taipei(*args) -> datetime:
    return TAIPEI.localize(datetime(*args))


def fake_cwa_payload(start: datetime, slots: list[tuple[str, int, int, str]]) -> dict:
    """依中央氣象署 F-D0047-091 的格式產生預報資料，每段 12 小時。"""
    fields = [("天氣現象", "Weather"), ("最低溫度", "MinTemperature"),
              ("最高溫度", "MaxTemperature"), ("12小時降雨機率", "ProbabilityOfPrecipitation")]
    from datetime import timedelta
    return {"records": {"Locations": [{"Location": [{"WeatherElement": [
        {"ElementName": name, "Time": [
            {"StartTime": (start + timedelta(hours=12 * i)).isoformat(), "ElementValue": [{key: str(slot[col])}]}
            for i, slot in enumerate(slots)
        ]}
        for col, (name, key) in enumerate(fields)
    ]}]}]}}


# 一週的假預報（從 10/20 06:00 開始）：明天下雨、後天很熱、週五偏冷
WEEK_SLOTS = [
    ("多雲時晴", 21, 27, "10"), ("晴時多雲", 20, 23, "0"),
    ("多雲短暫陣雨", 22, 26, "60"), ("陰短暫雨", 21, 23, "70"),
    ("晴時多雲", 23, 31, "10"), ("多雲", 22, 25, "20"),
    ("多雲", 14, 19, "30"), ("陰", 13, 16, "40"),
    ("晴", 18, 26, "0"), ("晴", 15, 18, "0"),
    ("多雲", 19, 25, "20"), ("多雲", 18, 21, "-"),
    ("多雲", 20, 26, "-"), ("多雲", 19, 22, "-"),
]


@pytest.fixture
def week_forecast():
    from app.search_modules.weather import parse_daily_forecast
    return parse_daily_forecast(fake_cwa_payload(taipei(2026, 10, 20, 6, 0), WEEK_SLOTS))
