from datetime import date, time

import pytest

from app.utils.time_utils import advance_daily, find_dates, format_day, format_run_at, next_daily_run
from tests.conftest import taipei

TUESDAY = date(2026, 10, 20)


def test_next_daily_run_later_today(now):
    assert next_daily_run(time(15, 0), now) == taipei(2026, 10, 20, 15, 0)


@pytest.mark.parametrize("at", [time(8, 0), time(14, 30)])
def test_next_daily_run_passed_or_now_goes_to_tomorrow(now, at):
    assert next_daily_run(at, now).date() == date(2026, 10, 21)


def test_advance_daily_skips_missed_days_once(now):
    assert advance_daily(taipei(2026, 10, 17, 8, 0), now) == taipei(2026, 10, 21, 8, 0)


def test_advance_daily_keeps_future_time(now):
    future = taipei(2026, 10, 22, 8, 0)
    assert advance_daily(future, now) == future


@pytest.mark.parametrize("run_at, repeat, expected", [
    ((2026, 10, 20, 15, 30), False, "今天 15:30"),
    ((2026, 10, 21, 8, 0), False, "明天 08:00"),
    ((2026, 10, 22, 8, 0), False, "後天 08:00"),
    ((2026, 10, 26, 15, 30), False, "10/26（一）15:30"),
    ((2026, 10, 21, 8, 0), True, "每天 08:00"),
])
def test_format_run_at(now, run_at, repeat, expected):
    assert format_run_at(taipei(*run_at), repeat, now) == expected


@pytest.mark.parametrize("today, text, expected", [
    (TUESDAY, "明天會下雨嗎", ["10-21"]),
    (TUESDAY, "後天台北", ["10-22"]),
    (TUESDAY, "大後天天氣", ["10-23"]),
    (TUESDAY, "今晚冷嗎", ["10-20"]),
    (TUESDAY, "昨天下雨", ["10-19"]),
    (TUESDAY, "週六天氣", ["10-24"]),
    (TUESDAY, "星期二天氣", ["10-20"]),
    (TUESDAY, "週一天氣", ["10-26"]),
    (TUESDAY, "下週一", ["10-26"]),
    (TUESDAY, "下週二", ["10-27"]),
    (TUESDAY, "禮拜天", ["10-25"]),
    (TUESDAY, "這週五", ["10-23"]),
    (TUESDAY, "週末冷不冷", ["10-24", "10-25"]),
    (TUESDAY, "下週末", ["10-31", "11-01"]),
    (date(2026, 10, 24), "週末", ["10-24", "10-25"]),
    (date(2026, 10, 25), "週末", ["10-25"]),
    (date(2026, 10, 25), "下週末", ["10-31", "11-01"]),
    (TUESDAY, "台北天氣", []),
])
def test_find_dates(today, text, expected):
    assert [d.strftime("%m-%d") for d in find_dates(text, today)] == expected


@pytest.mark.parametrize("day, expected", [
    (date(2026, 10, 20), "今天"),
    (date(2026, 10, 21), "明天"),
    (date(2026, 10, 22), "後天"),
    (date(2026, 10, 24), "10/24（六）"),
])
def test_format_day(day, expected):
    assert format_day(day, TUESDAY) == expected
