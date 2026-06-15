# app/utils/logger.py
"""統一的日誌管理系統"""
import copy
import logging
import os
import sys
from datetime import datetime
from pathlib import Path

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
    console_handler = logging.StreamHandler(sys.stdout)
    console_formatter = ColoredFormatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    console_handler.setFormatter(console_formatter)
    logger.addHandler(console_handler)
    
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
    logger.addHandler(file_handler)
    
    return logger


def configure_root_logging(level: str | None = None) -> None:
    """Route third-party logs to stdout so platforms do not mark INFO as errors."""
    resolved_level = (level or os.getenv("LOG_LEVEL", "INFO")).upper()
    root_logger = logging.getLogger()
    root_logger.setLevel(getattr(logging, resolved_level, logging.INFO))

    for handler in root_logger.handlers:
        root_logger.removeHandler(handler)

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter("%(levelname)s:%(name)s:%(message)s"))
    root_logger.addHandler(handler)


configure_root_logging()

# 全域日誌記錄器
main_logger = setup_logger("G-Bot")
