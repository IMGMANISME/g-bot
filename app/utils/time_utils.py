# app/utils/time_utils.py
"""台北時間與提醒排程的時間計算"""
import re
from datetime import date, datetime, time as dtime, timedelta

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


_RELATIVE_DAYS = (
    # 長的詞放前面，避免「大後天」被當成「後天」
    ("大後天", 3), ("前天", -2), ("昨天", -1), ("昨晚", -1),
    ("今天", 0), ("今日", 0), ("今晚", 0), ("今早", 0),
    ("明天", 1), ("明日", 1), ("明早", 1), ("明晚", 1), ("後天", 2),
)
_WEEKDAY_PATTERN = re.compile(r"(下個?|這個?|本)?(?:週|周|星期|禮拜)([一二三四五六日天])")
_WEEKEND_PATTERN = re.compile(r"(下個?|這個?|本)?(?:週末|周末)")
_WEEKDAY_INDEX = {name: i for i, name in enumerate(WEEKDAY_NAMES)} | {"天": 6}


def _weekday_date(today: date, weekday: int, next_week: bool) -> date:
    if next_week:
        next_monday = today + timedelta(days=7 - today.weekday())
        return next_monday + timedelta(days=weekday)
    return today + timedelta(days=(weekday - today.weekday()) % 7)


def find_dates(text: str, today: date) -> list[date]:
    """從句子找出指的日期：今天、明天、後天、週六、下週一、週末……；找不到回傳空清單。

    週末回傳週六與週日；沒加「下」的星期幾指接下來最近的那一天。可能包含過去的日期（昨天）。
    """
    text = text or ""
    for word, offset in _RELATIVE_DAYS:
        if word in text:
            return [today + timedelta(days=offset)]

    weekend = _WEEKEND_PATTERN.search(text)
    if weekend:
        monday = today - timedelta(days=today.weekday())
        if weekend.group(1) and weekend.group(1).startswith("下"):
            monday += timedelta(days=7)
        # 本週末＝這週六、日中還沒過的天（今天是週日時只剩今天）
        return [d for d in (monday + timedelta(days=5), monday + timedelta(days=6)) if d >= today]

    weekday = _WEEKDAY_PATTERN.search(text)
    if weekday:
        next_week = bool(weekday.group(1) and weekday.group(1).startswith("下"))
        return [_weekday_date(today, _WEEKDAY_INDEX[weekday.group(2)], next_week)]

    return []


def format_day(day: date, today: date) -> str:
    """今天、明天、後天，或 10/26（一）"""
    labels = {0: "今天", 1: "明天", 2: "後天"}
    offset = (day - today).days
    if offset in labels:
        return labels[offset]
    return f"{day:%m/%d}（{WEEKDAY_NAMES[day.weekday()]}）"
