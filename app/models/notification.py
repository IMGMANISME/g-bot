from sqlalchemy import Column, String, Integer, DateTime, Boolean, Time
from datetime import datetime
from app.models.base import Base

class ScheduledNotification(Base):
    __tablename__ = "scheduled_notifications"
    id = Column(Integer, primary_key=True, autoincrement=True)
    sender_id = Column(String, index=True)  # 聊天室 ID
    message = Column(String)
    repeat_daily = Column(Boolean, nullable=False, default=False)
    next_run_at = Column(DateTime(timezone=True), nullable=False, index=True)  # 下一次要送出的時間
    # 週期提醒：每隔 interval_minutes 分鐘提醒一次，只在 window_start～window_end 之間（可跨午夜；都是 NULL 代表整天）
    interval_minutes = Column(Integer, nullable=True)
    window_start = Column(Time, nullable=True)
    window_end = Column(Time, nullable=True)
    last_done_at = Column(DateTime(timezone=True), nullable=True)  # 使用者最近一次回報「做完了」
    # 一對一聊天時，使用者傳訊息就順便提醒（回覆不花推播額度）的最短間隔；NULL 代表用 interval 的 1/3
    nudge_interval_minutes = Column(Integer, nullable=True)
    last_reminded_at = Column(DateTime(timezone=True), nullable=True)  # 最近一次推播、順便提醒或回報完成
    created_at = Column(DateTime, default=datetime.utcnow)
