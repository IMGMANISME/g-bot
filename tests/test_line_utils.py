import pytest
from linebot.v3.messaging import ApiException, TextMessage

import app.utils.line_utils as line_utils
from app.utils.line_utils import PushResult


class FakeApi:
    def __init__(self, error=None):
        self.error = error
        self.pushes = []
        self.loading = []

    def push_message(self, request, x_line_retry_key=None):
        self.pushes.append((request.to, [m.text for m in request.messages if hasattr(m, "text")], x_line_retry_key))
        if self.error:
            raise self.error

    def show_loading_animation(self, request):
        self.loading.append((request.chat_id, request.loading_seconds))


def api_error(status):
    error = ApiException(status=status, reason="x")
    error.body = '{"message": "x"}'
    return error


@pytest.mark.parametrize("error, expected", [
    (None, PushResult.SENT),
    (api_error(409), PushResult.SENT),  # 同一個 retry key 先前已送出
    (api_error(500), PushResult.RETRY),
    (api_error(503), PushResult.RETRY),
    (api_error(400), PushResult.FAILED),
    (api_error(403), PushResult.FAILED),
    (ConnectionError("timeout"), PushResult.RETRY),
])
def test_push_result_by_status(monkeypatch, error, expected):
    monkeypatch.setattr(line_utils, "messaging_api", FakeApi(error))
    assert line_utils.push_message("U1", TextMessage(text="hi")) is expected


def test_push_to_users_uses_stable_retry_key_per_recipient(monkeypatch):
    api = FakeApi()
    monkeypatch.setattr(line_utils, "messaging_api", api)
    line_utils.push_line_message_to_users("地震", ["U1", "U2"], retry_key_base="earthquake:115069")
    line_utils.push_line_message_to_users("地震", ["U1"], retry_key_base="earthquake:115069")
    keys = [key for _, _, key in api.pushes]
    assert keys[0] == keys[2]  # 同一則推播、同一個人 → 同一個 key
    assert keys[0] != keys[1]  # 不同的人 → 不同的 key
    assert all(len(key) == 36 for key in keys)  # UUID 格式


def test_push_without_retry_key_base(monkeypatch):
    api = FakeApi()
    monkeypatch.setattr(line_utils, "messaging_api", api)
    assert line_utils.push_line_message_to_users("hi", ["U1"]) is PushResult.SENT
    assert api.pushes[0][2] is None


def test_push_to_users_reports_worst_result(monkeypatch):
    class MixedApi(FakeApi):
        def push_message(self, request, x_line_retry_key=None):
            if request.to == "U_blocked":
                raise api_error(400)

    monkeypatch.setattr(line_utils, "messaging_api", MixedApi())
    assert line_utils.push_line_message_to_users("hi", ["U1", "U_blocked"]) is PushResult.FAILED


@pytest.mark.parametrize("chat_id, shown", [("U123", True), ("C123", False), ("R123", False)])
def test_loading_animation_only_in_one_on_one(monkeypatch, chat_id, shown):
    api = FakeApi()
    monkeypatch.setattr(line_utils, "messaging_api", api)

    class InlineThread:
        def __init__(self, target, daemon):
            self.target = target

        def start(self):
            self.target()

    monkeypatch.setattr(line_utils.threading, "Thread", InlineThread)
    line_utils.show_loading_animation(chat_id)
    assert (api.loading == [(chat_id, 20)]) is shown


def test_message_quota(monkeypatch):
    class QuotaApi:
        def get_message_quota(self):
            return type("Quota", (), {"type": "limited", "value": 200})()

        def get_message_quota_consumption(self):
            return type("Usage", (), {"total_usage": 37})()

    monkeypatch.setattr(line_utils, "messaging_api", QuotaApi())
    assert line_utils.get_message_quota() == {"type": "limited", "limit": 200, "used": 37}


def test_message_quota_failure_is_reported(monkeypatch):
    class BrokenApi:
        def get_message_quota(self):
            raise api_error(401)

    monkeypatch.setattr(line_utils, "messaging_api", BrokenApi())
    assert "error" in line_utils.get_message_quota()
