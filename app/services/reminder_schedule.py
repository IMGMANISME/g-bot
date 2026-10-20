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


def make_window(start: time | None, end: time | None) -> Window | None:
    """兩者都有且不相同才算有時段；相同或缺少代表整天"""
    if start is None or end is None or start == end:
        return None
    return Window(start, end)


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
