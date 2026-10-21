# app/services/reminder_schedule.py
"""週期提醒的時間計算：每隔一段時間提醒，只在每天的某個時段內（可跨午夜）。"""
from dataclasses import dataclass
from datetime import datetime, time, timedelta

from app.utils.time_utils import TAIPEI, to_taipei

MINUTES_PER_DAY = 24 * 60


@dataclass(frozen=True)
class Window:
    """每天提醒的時段（含頭尾）；end 早於 start 代表跨午夜，例如 22:00–02:00。"""
    start: time
    end: time

    @property
    def crosses_midnight(self) -> bool:
        return self.end < self.start

    @property
    def length_minutes(self) -> int:
        start = self.start.hour * 60 + self.start.minute
        end = self.end.hour * 60 + self.end.minute
        return (end - start) % MINUTES_PER_DAY

    def contains(self, moment: datetime) -> bool:
        t = to_taipei(moment).time().replace(second=0, microsecond=0)
        if self.crosses_midnight:
            return t >= self.start or t <= self.end
        return self.start <= t <= self.end

    def next_start_after(self, moment: datetime) -> datetime:
        """moment 之後（含）最近一次的時段開始時間"""
        moment = to_taipei(moment)
        start = TAIPEI.localize(datetime.combine(moment.date(), self.start))
        return start if start >= moment else start + timedelta(days=1)

    def describe(self) -> str:
        return f"{self.start:%H:%M}–{self.end:%H:%M}"


# 時段長度至少這麼多分鐘就當作整天（模型有時把「整天」填成 00:00–23:59）
ALL_DAY_MINUTES = MINUTES_PER_DAY - 2


def make_window(start: time | None, end: time | None) -> Window | None:
    """兩者都有且不相同才算有時段；相同、缺少或幾乎涵蓋整天都代表整天"""
    if start is None or end is None or start == end:
        return None
    window = Window(start, end)
    return None if window.length_minutes >= ALL_DAY_MINUTES else window


def next_interval_run(previous: datetime, interval_minutes: int, window: Window | None, now: datetime) -> datetime:
    """上一次（或建立、完成）時間之後的下一次提醒：每隔 interval 一次、晚於 now，超出時段就等下一個時段開始。"""
    step = timedelta(minutes=interval_minutes)
    previous, now = to_taipei(previous), to_taipei(now)
    candidate = previous + step
    if candidate <= now:
        candidate += ((now - candidate) // step + 1) * step
    if window is None or window.contains(candidate):
        return candidate
    return window.next_start_after(candidate)


def runs_per_day(interval_minutes: int, window: Window | None) -> int:
    if window is None:
        return max(1, MINUTES_PER_DAY // interval_minutes)
    return window.length_minutes // interval_minutes + 1


def describe_interval(interval_minutes: int) -> str:
    hours, minutes = divmod(interval_minutes, 60)
    if not hours:
        return f"每 {minutes} 分鐘"
    if not minutes:
        return f"每 {hours} 小時"
    return f"每 {hours} 小時 {minutes} 分鐘"


def describe_recurrence(interval_minutes: int, window: Window | None) -> str:
    """每 2 小時（09:00–21:00）、每 30 分鐘（整天）"""
    return f"{describe_interval(interval_minutes)}（{window.describe() if window else '整天'}）"


def parse_clock(value) -> time | None:
    """「09:00」「9:00」→ time；看不懂回傳 None"""
    try:
        hour, minute = str(value).strip().split(":")
        return time(int(hour), int(minute))
    except (ValueError, AttributeError):
        return None


def default_nudge_interval(interval_minutes: int) -> int:
    """順便提醒的間隔：預設是推播間隔的 1/3（每 3 小時推播 → 有聊天時每 1 小時順便提醒）"""
    return max(1, interval_minutes // 3)


def is_nudge_due(
    interval_minutes: int,
    nudge_interval_minutes: int | None,
    window: Window | None,
    next_run_at: datetime,
    last_reminded_at: datetime | None,
    now: datetime,
) -> bool:
    """使用者傳訊息時，是否該順便提醒：在時段內，且距離上次提醒已超過順便提醒的間隔"""
    if window is not None and not window.contains(now):
        return False
    # 還沒提醒過時，以「上一個排定時間」當作上次提醒
    last = to_taipei(last_reminded_at) if last_reminded_at else to_taipei(next_run_at) - timedelta(minutes=interval_minutes)
    nudge = nudge_interval_minutes or default_nudge_interval(interval_minutes)
    return to_taipei(now) - last >= timedelta(minutes=nudge)


def skip_today_run(interval_minutes: int, window: Window | None, now: datetime) -> datetime:
    """「今天不用了」：跳到下一個時段開始；沒有時段的話明天同一時間"""
    now = to_taipei(now)
    if window is None:
        return now + timedelta(days=1)
    if window.contains(now):
        # 目前在時段內：這個時段剩下的都不提醒，等下一次時段開始
        return window.next_start_after(now + timedelta(minutes=1))
    next_start = window.next_start_after(now)
    # 今天的時段還沒開始：今天的也跳過
    return next_start + timedelta(days=1) if next_start.date() == now.date() else next_start
