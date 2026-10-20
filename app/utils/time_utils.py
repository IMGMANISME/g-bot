# app/utils/time_utils.py
"""台北時間與提醒排程的時間計算"""
from datetime import datetime, time as dtime, timedelta

import pytz

TAIPEI = pytz.timezone("Asia/Taipei")
WEEKDAY_NAMES = "一二三四五六日"
ONE_DAY = timedelta(days=1)


def now_taipei() -> datetime:
    return datetime.now(TAIPEI)


def to_taipei(value: datetime) -> datetime:
    """轉成台北時間；沒有時區資訊的 datetime 視為 UTC（SQLAlchemy 預設存法）。"""
    if value.tzinfo is None:
        value = pytz.utc.localize(value)
    return value.astimezone(TAIPEI)


def next_daily_run(at: dtime, now: datetime) -> datetime:
    """回傳下一次到達每日時間 at 的台北時間（若今天已過則為明天）。"""
    now = to_taipei(now)
    candidate = TAIPEI.localize(datetime.combine(now.date(), at.replace(second=0, microsecond=0)))
    if candidate <= now:
        candidate += ONE_DAY
    return candidate


def advance_daily(run_at: datetime, now: datetime) -> datetime:
    """每日提醒送出後，往後推到下一個晚於 now 的時間；錯過多天只算一次。"""
    run_at, now = to_taipei(run_at), to_taipei(now)
    if run_at > now:
        return run_at
    missed_days = (now - run_at) // ONE_DAY + 1
    return run_at + missed_days * ONE_DAY


def format_run_at(run_at: datetime, repeat_daily: bool, now: datetime) -> str:
    """把提醒時間轉成口語：每天 08:00、今天 15:30、明天 08:00、10/26（一）15:30。"""
    run_at, now = to_taipei(run_at), to_taipei(now)
    clock = run_at.strftime("%H:%M")
    if repeat_daily:
        return f"每天 {clock}"

    days_ahead = (run_at.date() - now.date()).days
    if days_ahead == 0:
        return f"今天 {clock}"
    if days_ahead == 1:
        return f"明天 {clock}"
    if days_ahead == 2:
        return f"後天 {clock}"
    return f"{run_at:%m/%d}（{WEEKDAY_NAMES[run_at.weekday()]}）{clock}"
