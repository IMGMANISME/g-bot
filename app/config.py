# app/config.py
"""應用程式配置管理"""
import os
from typing import List
from dataclasses import dataclass, field


def _get_int(name: str, default: int) -> int:
    """Read an integer environment variable with a safe fallback."""
    try:
        return int(os.getenv(name, default))
    except (TypeError, ValueError):
        return default


def _get_float(name: str, default: float) -> float:
    """Read a float environment variable with a safe fallback."""
    try:
        return float(os.getenv(name, default))
    except (TypeError, ValueError):
        return default


def _get_list(name: str, default: str, *, lowercase: bool = False) -> List[str]:
    value = os.getenv(name, default)
    items = [item.strip() for item in value.split(",") if item.strip()]
    if lowercase:
        return [item.lower() for item in items]
    return items


@dataclass
class Config:
    """應用程式配置類"""
    # LINE Bot 配置
    LINE_CHANNEL_ACCESS_TOKEN: str = os.getenv("LINE_CHANNEL_ACCESS_TOKEN")
    LINE_CHANNEL_SECRET: str = os.getenv("LINE_CHANNEL_SECRET")
    
    # Gemini AI 配置
    GEMINI_API_KEY: str = os.getenv("GEMINI_API_KEY")
    GEMINI_MODEL: str = os.getenv("GEMINI_MODEL", "gemma-4-26b-a4b-it")
    GEMINI_TEMPERATURE: float = _get_float("GEMINI_TEMPERATURE", 0.7)
    GEMINI_MAX_TOKENS: int = _get_int("GEMINI_MAX_TOKENS", 2048)
    
    # 資料庫配置
    DATABASE_URL: str = os.getenv("DATABASE_URL")
    
    # 應用程式配置
    MENTION_KEYWORDS: List[str] = field(
        default_factory=lambda: _get_list("MENTION_KEYWORDS", "@G-bot", lowercase=True)
    )
    
    # 管理員配置
    ADMIN_USERS: List[str] = field(
        default_factory=lambda: _get_list("ADMIN_USERS", "G-MAN,以馨,陳均葦")
    )
    
    # 地震監控配置
    EARTHQUAKE_CHECK_INTERVAL: int = _get_int("EARTHQUAKE_CHECK_INTERVAL", 20)
    EARTHQUAKE_MIN_MAGNITUDE: float = _get_float("EARTHQUAKE_MIN_MAGNITUDE", 4.0)
    EARTHQUAKE_MAX_LATENCY: int = _get_int("EARTHQUAKE_MAX_LATENCY", 900)  # 15 minutes
    
    # Loading Animation 配置
    ENABLE_LOADING_ANIMATION: bool = os.getenv("ENABLE_LOADING_ANIMATION", "true").lower() == "true"
    
    # 餐廳搜尋預設值
    DEFAULT_SEARCH_RADIUS: int = _get_int("DEFAULT_SEARCH_RADIUS", 1500)
    NEAR_RADIUS: int = _get_int("NEAR_RADIUS", 500)
    FAR_RADIUS: int = _get_int("FAR_RADIUS", 2500)

    # Tavily Search 配置
    TAVILY_API_KEY: str = os.getenv("TAVILY_API_KEY")
    TAVILY_SEARCH_MAX_RESULTS: int = _get_int("TAVILY_SEARCH_MAX_RESULTS", 5)
    TAVILY_SEARCH_DEPTH: str = os.getenv("TAVILY_SEARCH_DEPTH", "basic")
    TAVILY_SEARCH_TOPIC: str = os.getenv("TAVILY_SEARCH_TOPIC", "general")
    TAVILY_INCLUDE_ANSWER: bool = os.getenv("TAVILY_INCLUDE_ANSWER", "true").lower() == "true"

# 全域配置實例
config = Config()

# 驗證必要的環境變數
def validate_config():
    """驗證必要的配置項目"""
    required_vars = [
        "LINE_CHANNEL_ACCESS_TOKEN",
        "LINE_CHANNEL_SECRET", 
        "GEMINI_API_KEY",
        "DATABASE_URL"
    ]
    
    missing_vars = []
    for var in required_vars:
        if not getattr(config, var):
            missing_vars.append(var)
    
    if missing_vars:
        raise ValueError(f"缺少必要的環境變數: {', '.join(missing_vars)}")

if __name__ == "__main__":
    validate_config()
    print("✅ 配置驗證通過")
