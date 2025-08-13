# app/utils/performance.py
"""效能監控工具"""
import time
import psutil
import threading
from typing import Dict, Any, Optional
from datetime import datetime, timedelta
from collections import defaultdict, deque
from dataclasses import dataclass
from app.utils.logger import setup_logger

logger = setup_logger("performance")

@dataclass
class MetricData:
    """指標資料"""
    value: float
    timestamp: datetime

class PerformanceMonitor:
    """效能監控器"""
    
    def __init__(self, max_history: int = 1000):
        self.max_history = max_history
        self.metrics: Dict[str, deque] = defaultdict(lambda: deque(maxlen=max_history))
        self.counters: Dict[str, int] = defaultdict(int)
        self._lock = threading.RLock()
        self._start_time = time.time()
    
    def record_metric(self, name: str, value: float):
        """記錄指標值"""
        with self._lock:
            metric = MetricData(value=value, timestamp=datetime.now())
            self.metrics[name].append(metric)
    
    def increment_counter(self, name: str, amount: int = 1):
        """增加計數器"""
        with self._lock:
            self.counters[name] += amount
    
    def get_metric_stats(self, name: str, minutes: int = 60) -> Dict[str, Any]:
        """取得指標統計資訊"""
        with self._lock:
            if name not in self.metrics:
                return {}
            
            cutoff_time = datetime.now() - timedelta(minutes=minutes)
            recent_metrics = [
                m for m in self.metrics[name] 
                if m.timestamp >= cutoff_time
            ]
            
            if not recent_metrics:
                return {}
            
            values = [m.value for m in recent_metrics]
            return {
                "count": len(values),
                "min": min(values),
                "max": max(values),
                "avg": sum(values) / len(values),
                "latest": values[-1] if values else 0,
                "period_minutes": minutes
            }
    
    def get_system_stats(self) -> Dict[str, Any]:
        """取得系統統計資訊"""
        try:
            cpu_percent = psutil.cpu_percent(interval=1)
            memory = psutil.virtual_memory()
            disk = psutil.disk_usage('/')
            
            return {
                "cpu_percent": cpu_percent,
                "memory_percent": memory.percent,
                "memory_used_mb": memory.used / 1024 / 1024,
                "memory_total_mb": memory.total / 1024 / 1024,
                "disk_percent": disk.percent,
                "disk_used_gb": disk.used / 1024 / 1024 / 1024,
                "disk_total_gb": disk.total / 1024 / 1024 / 1024,
                "uptime_seconds": time.time() - self._start_time
            }
        except Exception as e:
            logger.error(f"取得系統統計失敗: {e}")
            return {}
    
    def get_counters(self) -> Dict[str, int]:
        """取得所有計數器"""
        with self._lock:
            return dict(self.counters)
    
    def reset_counters(self):
        """重置所有計數器"""
        with self._lock:
            self.counters.clear()
    
    def get_performance_report(self) -> Dict[str, Any]:
        """取得完整的效能報告"""
        report = {
            "timestamp": datetime.now().isoformat(),
            "system": self.get_system_stats(),
            "counters": self.get_counters(),
            "metrics": {}
        }
        
        # 添加主要指標統計
        for metric_name in self.metrics.keys():
            report["metrics"][metric_name] = self.get_metric_stats(metric_name)
        
        return report

def timing_decorator(metric_name: str = None):
    """執行時間監控裝飾器"""
    def decorator(func):
        name = metric_name or f"{func.__module__}.{func.__name__}"
        
        def wrapper(*args, **kwargs):
            start_time = time.time()
            try:
                result = func(*args, **kwargs)
                return result
            finally:
                execution_time = (time.time() - start_time) * 1000  # 轉換為毫秒
                performance_monitor.record_metric(f"{name}_duration_ms", execution_time)
                performance_monitor.increment_counter(f"{name}_calls")
        
        return wrapper
    return decorator

def monitor_function_calls(func):
    """監控函數調用次數"""
    def wrapper(*args, **kwargs):
        performance_monitor.increment_counter(f"{func.__name__}_calls")
        return func(*args, **kwargs)
    return wrapper

class DatabaseMetrics:
    """資料庫效能指標"""
    
    @staticmethod
    def record_query_time(query_type: str, duration_ms: float):
        """記錄查詢時間"""
        performance_monitor.record_metric(f"db_{query_type}_duration_ms", duration_ms)
        performance_monitor.increment_counter(f"db_{query_type}_count")
    
    @staticmethod
    def record_connection_pool_stats(active: int, idle: int):
        """記錄連接池統計"""
        performance_monitor.record_metric("db_connections_active", active)
        performance_monitor.record_metric("db_connections_idle", idle)

# 全域效能監控器實例
performance_monitor = PerformanceMonitor()

if __name__ == "__main__":
    # 測試效能監控
    monitor = PerformanceMonitor()
    
    # 模擬一些指標
    import random
    for i in range(10):
        monitor.record_metric("test_response_time", random.uniform(50, 200))
        monitor.increment_counter("test_requests")
        time.sleep(0.1)
    
    print("指標統計:", monitor.get_metric_stats("test_response_time"))
    print("計數器:", monitor.get_counters())
    print("系統統計:", monitor.get_system_stats())
