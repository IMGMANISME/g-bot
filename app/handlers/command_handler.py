# app/handlers/command_handler.py
"""命令處理器模組"""
import re
from typing import Optional, Tuple
from abc import ABC, abstractmethod
from dataclasses import dataclass
from app.utils.logger import setup_logger
from app.utils.decorators import handle_exceptions

logger = setup_logger("command_handler")

@dataclass
class CommandResult:
    """命令執行結果"""
    success: bool
    message: str
    should_continue: bool = False

class BaseCommandHandler(ABC):
    """基礎命令處理器"""
    
    @abstractmethod
    def can_handle(self, command: str, context: dict) -> bool:
        """判斷是否能處理此命令"""
        pass
    
    @abstractmethod
    def handle(self, command: str, context: dict) -> CommandResult:
        """處理命令"""
        pass

class StatusCommandHandler(BaseCommandHandler):
    """狀態相關命令處理器"""
    
    def can_handle(self, command: str, context: dict) -> bool:
        return command.lower() in ["#狀態", "#安靜", "#說話", "#標記", "#都回"]
    
    @handle_exceptions("⚠️ 狀態設定失敗")
    def handle(self, command: str, context: dict) -> CommandResult:
        from app.repositories.user_repository import get_user_state, set_user_state
        
        state_id = context.get("state_id") or context.get("chat_id") or context.get("sender_id")
        command_lower = command.lower()
        
        if command_lower == "#狀態":
            status = self._get_user_states_cn(state_id)
            return CommandResult(True, f"狀態：{status}")
        
        elif command_lower == "#安靜":
            current_state = get_user_state(state_id)
            new_state = "silent_mention" if "mention" in current_state else "silent"
            set_user_state(state_id, new_state)
            return CommandResult(True, "⏸️ 我會保持安靜。")
        
        elif command_lower == "#說話":
            current_state = get_user_state(state_id)
            new_state = "mention" if "mention" in current_state else "active"
            set_user_state(state_id, new_state)
            return CommandResult(True, "▶️ 我又可以說話囉！")
        
        elif command_lower == "#標記":
            set_user_state(state_id, "mention")
            return CommandResult(True, "📌 標記我模式開啟。")
        
        elif command_lower == "#都回":
            set_user_state(state_id, "active")
            return CommandResult(True, "✅ 所有訊息我都會回覆。")
        
        return CommandResult(False, "未知的狀態命令")
    
    def _get_user_states_cn(self, sender_id: str) -> str:
        from app.repositories.user_repository import get_user_state
        
        status = get_user_state(sender_id)
        status_map = {
            "active": "正常運作中～",
            "silent": "靜音中～絕對不會打擾你！",
            "mention": "標記我模式開啟～只有在被標記時才會回覆！",
            "silent_mention": "靜音跟標記我模式都開啟中～取消靜音後也只有在被標記時才會回覆！"
        }
        return status_map.get(status, "罷工中～請稍後再試！")

class UtilityCommandHandler(BaseCommandHandler):
    """工具類命令處理器"""
    
    def can_handle(self, command: str, context: dict) -> bool:
        return command.lower() in ["#功能", "#清除", "#選單", "#幫助", "我的設定", "#設定"]
    
    @handle_exceptions("⚠️ 命令執行失敗")
    def handle(self, command: str, context: dict) -> CommandResult:
        command_lower = command.lower()
        
        if command_lower == "#功能":
            function_text = (
                "🛠️ 目前功能：\n"
                "• 餐廳推薦 - 傳送位置並輸入「吃什麼?」\n"
                "• 即時搜尋 - 輸入「...新聞」、「查一下...」或「...最新消息」\n"
                "• 未來五日縣市天氣查詢 - 輸入「...天氣」\n"
                "• 即時NBA戰績/比分查詢 - 輸入「...戰績」或「...比賽」\n"
                "• 每日提醒 - 輸入「我的提醒」\n"
                "• 地震通知 - 輸入「地震通知開」、「地震通知關」或「地震門檻 4.5」\n"
                "• 我的設定 - 查看回覆模式與地震通知\n"
                "• 任意查詢 - 問我任何問題，我都會盡力回覆ㄛ～"
            )
            return CommandResult(True, function_text)
        
        elif command_lower == "#清除":
            from app.repositories.message_repository import clear_history
            memory_id = context.get("memory_id") or context.get("sender_id")
            clear_history(memory_id)
            return CommandResult(True, "✅ 已清除對話紀錄。")
        
        elif command_lower in ["我的設定", "#設定"]:
            return CommandResult(True, self._build_settings_text(context))

        elif command_lower in ["#選單", "#幫助"]:
            # 這些需要特殊的 quick reply 處理，返回特殊標記
            return CommandResult(True, f"SPECIAL_REPLY:{command_lower}")
        
        return CommandResult(False, "未知的工具命令")

    def _build_settings_text(self, context: dict) -> str:
        from app.repositories.user_repository import get_user_state, get_earthquake_settings
        from app.config import config

        state_id = context.get("state_id") or context.get("chat_id") or context.get("sender_id")
        status = get_user_state(state_id)
        status_map = {
            "active": "所有訊息都回",
            "silent": "靜音",
            "mention": "只在被標記時回",
            "silent_mention": "靜音 + 標記模式",
        }
        earthquake = get_earthquake_settings(state_id)
        min_magnitude = earthquake["min_magnitude"] or config.EARTHQUAKE_MIN_MAGNITUDE
        return (
            "目前設定：\n"
            f"回覆模式：{status_map.get(status, status)}\n"
            f"地震通知：{'開' if earthquake['enabled'] else '關'}\n"
            f"地震門檻：規模 {min_magnitude}"
        )

class EarthquakeCommandHandler(BaseCommandHandler):
    """地震通知設定命令處理器"""

    def can_handle(self, command: str, context: dict) -> bool:
        return any(keyword in command for keyword in ["地震通知", "地震門檻", "地震設定"])

    @handle_exceptions("⚠️ 地震設定失敗")
    def handle(self, command: str, context: dict) -> CommandResult:
        import re
        from app.config import config
        from app.repositories.user_repository import (
            set_earthquake_subscription,
            set_earthquake_min_magnitude,
            get_earthquake_settings,
        )

        state_id = context.get("state_id") or context.get("chat_id") or context.get("sender_id")
        normalized = command.strip().lower()

        if any(word in normalized for word in ["關", "停", "off", "取消"]):
            set_earthquake_subscription(state_id, False)
            return CommandResult(True, "地震通知已關閉。")

        if any(word in normalized for word in ["開", "啟用", "on"]):
            set_earthquake_subscription(state_id, True)
            return CommandResult(True, "地震通知已開啟。")

        match = re.search(r"地震門檻\s*(\d+(?:\.\d+)?)", command)
        if match:
            magnitude = float(match.group(1))
            if magnitude < 0 or magnitude > 10:
                return CommandResult(False, "地震門檻請設定 0 到 10 之間的規模。")
            set_earthquake_min_magnitude(state_id, magnitude)
            return CommandResult(True, f"地震通知門檻已改成規模 {magnitude}。")

        settings = get_earthquake_settings(state_id)
        min_magnitude = settings["min_magnitude"] or config.EARTHQUAKE_MIN_MAGNITUDE
        return CommandResult(
            True,
            f"地震通知：{'開' if settings['enabled'] else '關'}\n地震門檻：規模 {min_magnitude}"
        )

class ReminderCommandHandler(BaseCommandHandler):
    """提醒相關命令處理器"""
    
    def can_handle(self, command: str, context: dict) -> bool:
        return any(keyword in command for keyword in ["提醒我", "取消提醒", "刪除全部提醒", "我的提醒"])
    
    @handle_exceptions("⚠️ 提醒設定失敗")
    def handle(self, command: str, context: dict) -> CommandResult:
        import re
        from app.repositories.notification_repository import (
            add_scheduled_notification, delete_notification_by_id,
            delete_all_notifications_for_user
        )
        
        sender_id = context.get("chat_id") or context.get("sender_id")
        
        # 設定提醒
        if "提醒我" in command:
            msg, time_str, repeat = self._parse_natural_reminder(command)
            if msg and time_str:
                add_scheduled_notification(sender_id, msg, time_str, repeat)
                return CommandResult(
                    True, 
                    f"⏰ 提醒已設定：{time_str}｜每天：{'是' if repeat else '否'}｜內容：「{msg}」"
                )
            return CommandResult(False, "❌ 提醒格式錯誤，請使用：提醒我 <內容> <時間>")
        
        # 取消特定提醒
        elif "取消提醒" in command:
            parts = command.split()
            if len(parts) > 1:
                try:
                    ids = [int(p) for p in parts[1:] if p.isdigit()]
                    results = []
                    for id_ in ids:
                        success = delete_notification_by_id(sender_id, id_)
                        results.append(
                            f"✅ 已刪除提醒（編號: {id_}）" if success 
                            else f"⚠️ 查無此提醒（編號: {id_}）"
                        )
                    return CommandResult(True, "\n".join(results))
                except ValueError:
                    return CommandResult(False, "❌ 提醒編號必須是數字")
            return CommandResult(False, "❌ 格式錯誤，請使用：取消提醒 <編號1> <編號2> ...")
        
        # 刪除全部提醒
        elif "刪除全部提醒" in command:
            deleted_count = delete_all_notifications_for_user(sender_id)
            return CommandResult(True, f"🗑️ 已清除 {deleted_count} 筆提醒。")
        
        # 查看提醒列表
        elif "我的提醒" in command:
            return CommandResult(True, "SPECIAL_REPLY:我的提醒")
        
        return CommandResult(False, "未知的提醒命令")
    
    def _parse_natural_reminder(self, text: str) -> Tuple[Optional[str], Optional[str], bool]:
        """解析自然語言提醒"""
        import re
        match = re.search(r"提醒我\s*(.+?)\s*(\d{1,2})[:點](\d{2})?\s*(每天|一次)?", text)
        if match:
            msg = match.group(1).strip()
            hour = int(match.group(2))
            minute = int(match.group(3)) if match.group(3) else 0
            repeat = (match.group(4) == "每天")
            return msg, f"{hour:02d}:{minute:02d}", repeat
        return None, None, False

class CommandProcessor:
    """命令處理器管理類"""
    
    def __init__(self):
        self.handlers = [
            StatusCommandHandler(),
            UtilityCommandHandler(),
            EarthquakeCommandHandler(),
            ReminderCommandHandler(),
        ]
    
    def _normalize_command(self, command: str, context: dict) -> str:
        """Normalize command text before handler matching.

        Group users often invoke commands by mentioning the bot first, e.g.
        "@G-bot #狀態".  Handlers should still receive the real command text.
        """
        normalized = command.strip()

        mention_keywords = context.get("mention_keywords") or []
        if not mention_keywords:
            try:
                from app.config import config
                mention_keywords = config.MENTION_KEYWORDS
            except Exception:
                mention_keywords = []

        for keyword in sorted(mention_keywords, key=lambda value: len(str(value)), reverse=True):
            keyword = str(keyword).strip()
            if not keyword:
                continue

            pattern = rf"^\s*{re.escape(keyword)}(?:\s|　|:|：|,|，)*"
            updated = re.sub(pattern, "", normalized, count=1, flags=re.IGNORECASE).strip()
            if updated != normalized:
                return updated

        return normalized

    def process_command(self, command: str, context: dict) -> Optional[CommandResult]:
        """處理命令"""
        command = self._normalize_command(command, context)
        for handler in self.handlers:
            if handler.can_handle(command, context):
                logger.info(f"使用處理器 {handler.__class__.__name__} 處理命令: {command}")
                result = handler.handle(command, context)
                if isinstance(result, CommandResult):
                    return result
                logger.error(f"{handler.__class__.__name__} 回傳非 CommandResult: {result!r}")
                return CommandResult(False, str(result) if result else "⚠️ 命令執行失敗")
        
        return None
    
    def add_handler(self, handler: BaseCommandHandler):
        """添加自定義命令處理器"""
        self.handlers.append(handler)

# 全域命令處理器實例
command_processor = CommandProcessor()
