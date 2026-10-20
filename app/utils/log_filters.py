# app/utils/log_filters.py
"""日誌過濾器（不能有副作用：uvicorn 載入 log 設定時就會匯入這個模組）"""
import logging


class BelowLevelFilter(logging.Filter):
    """只放行低於指定等級的紀錄。

    搭配兩個 handler 使用：INFO、WARNING 寫到 stdout，ERROR 以上寫到 stderr。
    Railway 等平台會把 stderr 一律標成錯誤，這樣標示才會正確。
    """

    def __init__(self, max_level: str | int = logging.ERROR):
        super().__init__()
        self.max_level = logging.getLevelName(max_level) if isinstance(max_level, str) else max_level

    def filter(self, record: logging.LogRecord) -> bool:
        return record.levelno < self.max_level
