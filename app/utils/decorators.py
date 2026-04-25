# app/utils/decorators.py
"""實用的裝飾器函數"""
import functools
from typing import Callable
from app.utils.logger import setup_logger

logger = setup_logger("decorators")

def handle_exceptions(
    fallback_message: str = "⚠️ 處理過程中發生錯誤，請稍後再試",
    log_error: bool = True,
    reraise: bool = False
):
    """例外處理裝飾器"""
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            try:
                return func(*args, **kwargs)
            except Exception as e:
                if log_error:
                    logger.error(f"函數 {func.__name__} 發生錯誤: {e}", exc_info=True)
                
                if reraise:
                    raise
                
                # 如果是 LINE 回覆相關的函數，嘗試回覆錯誤訊息
                if len(args) > 0 and hasattr(args[0], 'reply_token'):
                    try:
                        from app.utils.line_utils import safe_reply
                        safe_reply(args[0], fallback_message)
                    except:
                        pass
                
                return fallback_message
        return wrapper
    return decorator

def async_handle_exceptions(
    fallback_message: str = "⚠️ 處理過程中發生錯誤，請稍後再試",
    log_error: bool = True,
    reraise: bool = False
):
    """非同步例外處理裝飾器"""
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        async def wrapper(*args, **kwargs):
            try:
                return await func(*args, **kwargs)
            except Exception as e:
                if log_error:
                    logger.error(f"非同步函數 {func.__name__} 發生錯誤: {e}", exc_info=True)
                
                if reraise:
                    raise
                
                return fallback_message
        return wrapper
    return decorator

def retry_on_failure(
    max_retries: int = 3,
    delay: float = 1.0,
    backoff_factor: float = 2.0,
    exceptions: tuple = (Exception,)
):
    """重試裝飾器"""
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            for attempt in range(max_retries + 1):
                try:
                    return func(*args, **kwargs)
                except exceptions as e:
                    if attempt == max_retries:
                        logger.error(f"函數 {func.__name__} 重試 {max_retries} 次後仍然失敗: {e}")
                        raise
                    
                    wait_time = delay * (backoff_factor ** attempt)
                    logger.warning(f"函數 {func.__name__} 第 {attempt + 1} 次嘗試失敗，{wait_time:.1f}秒後重試: {e}")
                    
                    import time
                    time.sleep(wait_time)
            
            return None
        return wrapper
    return decorator

def rate_limit(calls_per_minute: int = 60):
    """速率限制裝飾器"""
    import time
    from collections import defaultdict
    
    call_times = defaultdict(list)
    
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            now = time.time()
            
            # 獲取調用者識別（如果有 sender_id）
            caller_id = "default"
            if args and hasattr(args[0], 'source'):
                caller_id = getattr(args[0].source, 'user_id', 'default')
            
            # 清理超過一分鐘的記錄
            call_times[caller_id] = [
                call_time for call_time in call_times[caller_id]
                if now - call_time < 60
            ]
            
            # 檢查是否超過限制
            if len(call_times[caller_id]) >= calls_per_minute:
                logger.warning(f"用戶 {caller_id} 觸發速率限制")
                if args and hasattr(args[0], 'reply_token'):
                    try:
                        from app.utils.line_utils import safe_reply
                        safe_reply(args[0], "⚠️ 請求過於頻繁，請稍後再試")
                    except Exception:
                        pass
                return "⚠️ 請求過於頻繁，請稍後再試"
            
            # 記錄此次調用
            call_times[caller_id].append(now)
            
            return func(*args, **kwargs)
        return wrapper
    return decorator
