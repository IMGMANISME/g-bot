"""一般訊息寫到 stdout、錯誤寫到 stderr：Railway 會把 stderr 一律標成錯誤。"""
import json
import logging
import logging.config
from pathlib import Path

import pytest

from app.utils.log_filters import BelowLevelFilter
from app.utils.logger import setup_logger

UVICORN_LOG_CONFIG = Path(__file__).resolve().parent.parent / "app" / "uvicorn_logging.json"


@pytest.mark.parametrize("level, passes", [
    (logging.DEBUG, True), (logging.INFO, True), (logging.WARNING, True),
    (logging.ERROR, False), (logging.CRITICAL, False),
])
def test_below_level_filter(level, passes):
    record = logging.LogRecord("x", level, __file__, 1, "msg", None, None)
    assert BelowLevelFilter("ERROR").filter(record) is passes


def test_app_logger_splits_by_level(capsys):
    logger = setup_logger("test_split_logger", level="INFO")
    logger.info("一般訊息")
    logger.warning("警告訊息")
    logger.error("錯誤訊息")
    out, err = capsys.readouterr()
    assert "一般訊息" in out and "警告訊息" in out and "錯誤訊息" not in out
    assert "錯誤訊息" in err and "一般訊息" not in err


def test_app_logger_still_redacts_api_keys(capsys):
    logger = setup_logger("test_redact_logger", level="INFO")
    logger.error("key=AIza" + "A" * 35)
    _, err = capsys.readouterr()
    assert "AIza***" in err and "A" * 35 not in err


@pytest.fixture
def restore_uvicorn_loggers():
    """測完還原 uvicorn logger，避免影響其他測試"""
    names = ("uvicorn", "uvicorn.error", "uvicorn.access")
    saved = {name: (logging.getLogger(name).handlers[:], logging.getLogger(name).propagate) for name in names}
    yield
    for name, (handlers, propagate) in saved.items():
        logger = logging.getLogger(name)
        logger.handlers, logger.propagate = handlers, propagate


def test_uvicorn_info_goes_to_stdout_and_errors_to_stderr(restore_uvicorn_loggers, capsys):
    # 在測試內套用設定：handler 才會寫到 capsys 攔截的 stdout／stderr
    logging.config.dictConfig(json.loads(UVICORN_LOG_CONFIG.read_text()))
    logging.getLogger("uvicorn.error").info("Uvicorn running on http://0.0.0.0:8080")
    logging.getLogger("uvicorn.error").error("Exception in ASGI application")
    logging.getLogger("uvicorn.access").info('%s - "%s %s HTTP/%s" %d', "1.2.3.4:5", "GET", "/health", "1.1", 200)
    out, err = capsys.readouterr()
    assert "Uvicorn running on" in out and "GET /health" in out
    assert "Exception in ASGI application" in err
    assert "Uvicorn running on" not in err
