from datetime import time

import pytest

from app.services.reminder_schedule import (
    Window, describe_recurrence, make_window, next_interval_run, parse_clock, runs_per_day,
)
from tests.conftest import taipei

DAYTIME = Window(time(9, 0), time(21, 0))
NIGHT = Window(time(22, 0), time(2, 0))  # 跨午夜


@pytest.mark.parametrize("window, moment, inside", [
    (DAYTIME, (9, 0), True), (DAYTIME, (21, 0), True), (DAYTIME, (8, 59), False), (DAYTIME, (21, 1), False),
    (NIGHT, (22, 0), True), (NIGHT, (23, 30), True), (NIGHT, (1, 0), True), (NIGHT, (2, 0), True),
    (NIGHT, (2, 1), False), (NIGHT, (12, 0), False),
])
def test_window_contains(window, moment, inside):
    assert window.contains(taipei(2026, 10, 20, *moment)) is inside


@pytest.mark.parametrize("previous, now, expected", [
    ((14, 30), (14, 30), (16, 30)),   # 建立時：現在 + 間隔
    ((19, 0), (19, 0), (21, 0)),      # 剛好在時段結尾，還要提醒
    ((21, 0), (21, 0), (9, 0, 1)),    # 超出時段 → 隔天早上
    ((22, 0), (22, 0), (9, 0, 1)),    # 在時段外建立 → 隔天時段開始
    ((7, 0), (7, 0), (9, 0)),         # 早上建立，剛好落在時段開頭
    ((9, 0), (13, 10), (15, 0)),      # 服務停了一陣子：跳過錯過的，不會一口氣補發
])
def test_next_interval_run_daytime(previous, now, expected):
    day_offset = expected[2] if len(expected) == 3 else 0
    result = next_interval_run(taipei(2026, 10, 20, *previous), 120, DAYTIME, taipei(2026, 10, 20, *now))
    assert result == taipei(2026, 10, 20 + day_offset, *expected[:2])


def test_next_interval_run_across_midnight():
    assert next_interval_run(taipei(2026, 10, 20, 23, 0), 60, NIGHT, taipei(2026, 10, 20, 23, 0)) == taipei(2026, 10, 21, 0, 0)
    assert next_interval_run(taipei(2026, 10, 21, 2, 0), 60, NIGHT, taipei(2026, 10, 21, 2, 0)) == taipei(2026, 10, 21, 22, 0)


def test_next_interval_run_without_window():
    assert next_interval_run(taipei(2026, 10, 20, 23, 30), 60, None, taipei(2026, 10, 20, 23, 30)) == taipei(2026, 10, 21, 0, 30)


@pytest.mark.parametrize("interval, window, expected", [
    (120, DAYTIME, 7),   # 9, 11, 13, 15, 17, 19, 21
    (60, NIGHT, 5),      # 22, 23, 0, 1, 2
    (5, DAYTIME, 145),
    (60, None, 24),
])
def test_runs_per_day(interval, window, expected):
    assert runs_per_day(interval, window) == expected


@pytest.mark.parametrize("interval, window, expected", [
    (120, DAYTIME, "每 2 小時（09:00–21:00）"),
    (30, None, "每 30 分鐘（整天）"),
    (90, NIGHT, "每 1 小時 30 分鐘（22:00–02:00）"),
])
def test_describe_recurrence(interval, window, expected):
    assert describe_recurrence(interval, window) == expected


def test_make_window_and_parse_clock():
    assert make_window(time(9), time(21)) == DAYTIME
    assert make_window(time(9), time(9)) is None  # 相同代表整天
    assert make_window(None, time(21)) is None
    assert parse_clock("9:05") == time(9, 5) and parse_clock("21:00") == time(21, 0)
    assert parse_clock("晚上九點") is None and parse_clock(None) is None and parse_clock("25:00") is None
