# app/utils/cache.py
"""簡單的記憶體快取系統"""
import time
import threading
from typing import Any, Optional, Dict
from dataclasses import dataclass
from app.utils.logger import setup_logger

logger = setup_logger("cache")

@dataclass
class CacheItem:
    """快取項目"""
    value: Any
    expire_time: float
    created_time: float

class MemoryCache:
    """記憶體快取類"""
    
    def __init__(self, default_ttl: int = 300):  # 預設5分鐘
        self.cache: Dict[str, CacheItem] = {}
        self.default_ttl = default_ttl
        self._lock = threading.RLock()
        self._cleanup_interval = 60  # 每分鐘清理一次
        self._last_cleanup = time.time()
    
    def get(self, key: str) -> Optional[Any]:
        """取得快取值"""
        with self._lock:
            self._cleanup_if_needed()
            
            if key not in self.cache:
                return None
            
            item = self.cache[key]
            if time.time() > item.expire_time:
                del self.cache[key]
                return None
            
            return item.value
    
    def set(self, key: str, value: Any, ttl: Optional[int] = None) -> None:
        """設定快取值"""
        if ttl is None:
            ttl = self.default_ttl
        
        expire_time = time.time() + ttl
        
        with self._lock:
            self.cache[key] = CacheItem(
                value=value,
                expire_time=expire_time,
                created_time=time.time()
            )
    
    def delete(self, key: str) -> bool:
        """刪除快取項目"""
        with self._lock:
            return self.cache.pop(key, None) is not None
    
    def clear(self) -> None:
        """清空所有快取"""
        with self._lock:
            self.cache.clear()
            logger.info("快取已清空")
    
    def _cleanup_if_needed(self) -> None:
        """如果需要，執行過期項目清理"""
        now = time.time()
        if now - self._last_cleanup < self._cleanup_interval:
            return
        
        expired_keys = []
        for key, item in self.cache.items():
            if now > item.expire_time:
                expired_keys.append(key)
        
        for key in expired_keys:
            del self.cache[key]
        
        if expired_keys:
            logger.debug(f"清理了 {len(expired_keys)} 個過期快取項目")
        
        self._last_cleanup = now
    
    def get_stats(self) -> Dict[str, Any]:
        """取得快取統計資訊"""
        with self._lock:
            self._cleanup_if_needed()
            
            now = time.time()
            valid_items = sum(1 for item in self.cache.values() if now <= item.expire_time)
            
            return {
                "total_items": len(self.cache),
                "valid_items": valid_items,
                "expired_items": len(self.cache) - valid_items,
                "memory_usage": len(str(self.cache))  # 簡單的記憶體使用估計
            }

def cache_result(ttl: int = 300, key_prefix: str = ""):
    """快取函數結果的裝飾器"""
    def decorator(func):
        def wrapper(*args, **kwargs):
            # 生成快取鍵
            cache_key = f"{key_prefix}:{func.__name__}:{hash(str(args) + str(kwargs))}"
            
            # 嘗試從快取取得結果
            cached_result = global_cache.get(cache_key)
            if cached_result is not None:
                logger.debug(f"快取命中: {cache_key}")
                return cached_result
            
            # 執行函數並快取結果
            result = func(*args, **kwargs)
            global_cache.set(cache_key, result, ttl)
            logger.debug(f"快取設定: {cache_key}")
            
            return result
        return wrapper
    return decorator

# 全域快取實例
global_cache = MemoryCache(default_ttl=300)

if __name__ == "__main__":
    # 測試快取功能
    cache = MemoryCache(default_ttl=5)
    
    cache.set("test", "value", 2)
    print(f"立即取得: {cache.get('test')}")
    
    time.sleep(3)
    print(f"3秒後: {cache.get('test')}")
    
    print(f"統計: {cache.get_stats()}")
