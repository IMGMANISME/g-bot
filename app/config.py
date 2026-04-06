# app/config.py
"""應用程式配置管理"""
import os
from typing import List
from dataclasses import dataclass, field

@dataclass
class Config:
    """應用程式配置類"""
    # LINE Bot 配置
    LINE_CHANNEL_ACCESS_TOKEN: str = os.getenv("LINE_CHANNEL_ACCESS_TOKEN")
    LINE_CHANNEL_SECRET: str = os.getenv("LINE_CHANNEL_SECRET")
    
    # Gemini AI 配置
    GEMINI_API_KEY: str = os.getenv("GEMINI_API_KEY")
    GEMINI_MODEL: str = "gemma-4-31b-it"
    GEMINI_TEMPERATURE: float = 0.7
    GEMINI_MAX_TOKENS: int = 2048
    
    # 資料庫配置
    DATABASE_URL: str = os.getenv("DATABASE_URL")
    
    # 應用程式配置
    MENTION_KEYWORDS: List[str] = field(
        default_factory=lambda: os.getenv("MENTION_KEYWORDS", "@G-bot").lower().split(",")
    )
    
    # 管理員配置
    ADMIN_USERS: List[str] = field(
        default_factory=lambda: os.getenv("ADMIN_USERS", "G-MAN,以馨,陳均葦").split(",")
    )
    
    # 地震監控配置
    EARTHQUAKE_CHECK_INTERVAL: int = 20
    EARTHQUAKE_MIN_MAGNITUDE: float = 4.0
    EARTHQUAKE_MAX_LATENCY: int = 900  # 15 minutes
    
    # Loading Animation 配置
    ENABLE_LOADING_ANIMATION: bool = os.getenv("ENABLE_LOADING_ANIMATION", "true").lower() == "true"
    
    # 餐廳搜尋預設值
    DEFAULT_SEARCH_RADIUS: int = 1500
    NEAR_RADIUS: int = 500
    FAR_RADIUS: int = 2500

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
