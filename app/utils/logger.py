# app/utils/logger.py
"""統一的日誌管理系統"""
import copy
import logging
import os
import re
import sys
from datetime import datetime
from pathlib import Path

from app.utils.log_filters import BelowLevelFilter

class ColoredFormatter(logging.Formatter):
    """帶顏色的日誌格式化器"""
    
    COLORS = {
        'DEBUG': '\033[36m',    # 青色
        'INFO': '\033[32m',     # 綠色
        'WARNING': '\033[33m',  # 黃色
        'ERROR': '\033[31m',    # 紅色
        'CRITICAL': '\033[35m', # 紫色
        'RESET': '\033[0m'      # 重置
    }
    
    def format(self, record):
        colored_record = copy.copy(record)
        color = self.COLORS.get(colored_record.levelname, self.COLORS['RESET'])
        colored_record.levelname = f"{color}{colored_record.levelname}{self.COLORS['RESET']}"
        return super().format(colored_record)

_GOOGLE_API_KEY_PATTERN = re.compile(r"AIza[0-9A-Za-z_\-]{35}")


def redact_secrets(text: str) -> str:
    """遮蔽日誌中的 API 金鑰，避免錯誤訊息把金鑰寫進 log。"""
    text = _GOOGLE_API_KEY_PATTERN.sub("AIza***", text)
    api_key = os.getenv("GEMINI_API_KEY")
    if api_key and len(api_key) >= 8:
        text = text.replace(api_key, "***")
    return text


class RedactSecretsFilter(logging.Filter):
    """在輸出前遮蔽訊息與 traceback 中的金鑰"""

    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = redact_secrets(record.getMessage())
        record.args = None
        if record.exc_info and not record.exc_text:
            record.exc_text = logging.Formatter().formatException(record.exc_info)
        if record.exc_text:
            record.exc_text = redact_secrets(record.exc_text)
        return True


_redact_filter = RedactSecretsFilter()


def _console_handlers(formatter: logging.Formatter) -> list[logging.Handler]:
    """INFO、WARNING 寫到 stdout，ERROR 以上寫到 stderr。

    Railway 會把 stderr 一律標成錯誤；分開輸出後，一般訊息不會被誤標，真正的錯誤也會被標出來。
    """
    stdout_handler = logging.StreamHandler(sys.stdout)
    stdout_handler.addFilter(BelowLevelFilter(logging.ERROR))
    stderr_handler = logging.StreamHandler(sys.stderr)
    stderr_handler.setLevel(logging.ERROR)
    for handler in (stdout_handler, stderr_handler):
        handler.setFormatter(formatter)
        handler.addFilter(_redact_filter)
    return [stdout_handler, stderr_handler]


def setup_logger(name: str, level: str | None = None) -> logging.Logger:
    """設置日誌記錄器"""
    resolved_level = (level or os.getenv("LOG_LEVEL", "INFO")).upper()
    logger = logging.getLogger(name)
    logger.setLevel(getattr(logging, resolved_level, logging.INFO))
    logger.propagate = False
    
    # 避免重複添加處理器
    if logger.handlers:
        return logger
    
    # 控制台處理器
    console_formatter = ColoredFormatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    for handler in _console_handlers(console_formatter):
        logger.addHandler(handler)
    
    # 檔案處理器（可選）
    log_dir = Path("logs")
    if not log_dir.exists():
        log_dir.mkdir(exist_ok=True)
    
    file_handler = logging.FileHandler(
        log_dir / f"{name}_{datetime.now().strftime('%Y%m%d')}.log",
        encoding='utf-8'
    )
    file_formatter = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(funcName)s:%(lineno)d - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    file_handler.setFormatter(file_formatter)
    file_handler.addFilter(_redact_filter)
    logger.addHandler(file_handler)
    
    return logger


def configure_root_logging(level: str | None = None) -> None:
    """第三方套件的日誌：一般訊息寫到 stdout、錯誤寫到 stderr，平台才能正確標示嚴重程度。"""
    resolved_level = (level or os.getenv("LOG_LEVEL", "INFO")).upper()
    root_logger = logging.getLogger()
    root_logger.setLevel(getattr(logging, resolved_level, logging.INFO))

    # APScheduler 每次執行 job 都會輸出 INFO（地震檢查每 20 秒一次），只保留 WARNING 以上
    logging.getLogger("apscheduler").setLevel(
        os.getenv("APSCHEDULER_LOG_LEVEL", "WARNING").upper()
    )

    # Alembic 每次啟動都會列出載入的外掛，只保留 WARNING 以上
    logging.getLogger("alembic.runtime.plugins").setLevel(logging.WARNING)

    if root_logger.handlers:
        for handler in root_logger.handlers:
            handler.setLevel(getattr(logging, resolved_level, logging.INFO))
            handler.addFilter(_redact_filter)
        return

    for handler in _console_handlers(logging.Formatter("%(levelname)s:%(name)s:%(message)s")):
        root_logger.addHandler(handler)


configure_root_logging()

# 全域日誌記錄器
main_logger = setup_logger("G-Bot")
