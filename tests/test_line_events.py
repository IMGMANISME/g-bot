"""用真實的 webhook 格式（含簽名）走完事件註冊流程，LINE API 與資料庫換成假的。"""
import base64
import hashlib
import hmac
import json

import pytest
from linebot import WebhookHandler

import app.handlers.events.location_event as location_event
import app.handlers.events.message_event as message_event
import app.handlers.events.welcome_event as welcome_event
import app.line_bot as line_bot
import app.repositories.user_repository as user_repository
import app.utils.line_utils as line_utils

SECRET = "test-secret"
USER = {"type": "user", "userId": "U1"}
MENTION_GROUP = {"type": "group", "groupId": "G_mention", "userId": "U2"}


@pytest.fixture
def bot(monkeypatch):
    state = {"replies": [], "locations": [], "states": {"G_mention": "mention"}}

    class FakeLineApi:
        def reply_message(self, token, message):
            state["replies"].append(message)

        def push_message(self, to, message):
            state["replies"].append(message)

    class SyncExecutor:
        def submit(self, fn):
            fn()

    fake = FakeLineApi()
    for module in (line_utils, welcome_event, message_event):
        monkeypatch.setattr(module, "line_bot_api", fake)
    monkeypatch.setattr(line_bot, "background_executor", SyncExecutor())
    get_state = lambda chat_id: state["states"].get(chat_id, "active")
    for module in (user_repository, location_event, message_event):
        monkeypatch.setattr(module, "get_user_state", get_state)
    monkeypatch.setattr(location_event, "upsert_user_location", lambda sid, lat, lng: state["locations"].append((sid, lat, lng)))
    monkeypatch.setattr(message_event, "get_user_notifications", lambda sid: [])

    handler = WebhookHandler(SECRET)
    line_bot.handle_events(handler)

    def send(event):
        body = json.dumps({"destination": "x", "events": [event]})
        signature = base64.b64encode(hmac.new(SECRET.encode(), body.encode(), hashlib.sha256).digest()).decode()
        state["replies"].clear()
        handler.handle(body, signature)
        return state["replies"][-1] if state["replies"] else None

    state["send"] = send
    return state


def event(kind, source, **extra):
    return {"type": kind, "mode": "active", "timestamp": 0, "webhookEventId": "w",
            "deliveryContext": {"isRedelivery": False}, "replyToken": "rt", "source": source, **extra}


def text_event(source, text):
    return event("message", source, message={"type": "text", "id": "1", "text": text, "quoteToken": "q"})


def location_event_payload(source):
    return event("message", source, message={"type": "location", "id": "1", "latitude": 25.03, "longitude": 121.56, "address": "x"})


def labels(message):
    return [b.action.label for b in message.quick_reply.items] if message.quick_reply else []


def button_texts(message):
    return [getattr(b.action, "text", None) for b in message.quick_reply.items] if message.quick_reply else []


def test_follow_sends_welcome(bot):
    reply = bot["send"](event("follow", USER))
    assert "我是 G-Bot" in reply.text and "#幫助" in reply.text
    assert labels(reply) == ["台北天氣", "10 分鐘後提醒我", "📍 傳送位置", "幫助"]
    assert type(reply.quick_reply.items[2].action).__name__ == "LocationAction"


def test_join_introduces_in_group(bot):
    reply = bot["send"](event("join", {"type": "group", "groupId": "G9"}))
    assert "#標記" in reply.text and "@G-bot" in reply.text
    assert labels(reply) == ["只在被叫時回", "台北天氣", "幫助"]


def test_location_is_saved_with_food_buttons(bot):
    reply = bot["send"](location_event_payload(USER))
    assert bot["locations"] == [("U1", 25.03, 121.56)]
    assert "直接問我" in reply.text
    assert button_texts(reply) == ["附近有什麼好吃的", "吃什麼 便宜", "吃什麼 近一點", "吃什麼 拉麵"]


def test_location_buttons_in_mention_mode_call_the_bot(bot):
    reply = bot["send"](location_event_payload(MENTION_GROUP))
    assert "標記我" in reply.text
    assert all(text.startswith("@G-bot ") for text in button_texts(reply))


def test_cancel_reminder_without_id_shows_example(bot):
    reply = bot["send"](text_event(USER, "取消提醒"))
    assert "例如「取消提醒 3」" in reply.text and button_texts(reply) == ["我的提醒"]


def test_earthquake_threshold_out_of_range_shows_examples(bot):
    reply = bot["send"](text_event(MENTION_GROUP, "@G-bot 地震門檻 12"))
    assert "0 到 10" in reply.text
    assert button_texts(reply) == ["@G-bot 地震門檻 4.0", "@G-bot 地震門檻 4.5", "@G-bot 地震門檻 5.0"]


def test_empty_reminder_list_shows_example(bot):
    reply = bot["send"](text_event(USER, "我的提醒"))
    assert "📭" in reply.text and button_texts(reply) == ["10分鐘後提醒我喝水"]


def test_plain_command_has_no_buttons(bot):
    reply = bot["send"](text_event(USER, "#狀態"))
    assert reply.text.startswith("狀態：") and reply.quick_reply is None


def test_mention_mode_ignores_messages_without_mention(bot, monkeypatch):
    called = []
    monkeypatch.setattr(message_event, "get_assistant_reply", lambda **kwargs: called.append(kwargs))
    assert bot["send"](text_event(MENTION_GROUP, "大家晚安")) is None
    assert called == []


def test_message_goes_to_assistant_with_mention_removed(bot, monkeypatch):
    from app.services.assistant_service import AssistantReply
    seen = {}

    def fake_reply(**kwargs):
        seen.update(kwargs)
        return AssistantReply("好喔")

    monkeypatch.setattr(message_event, "get_assistant_reply", fake_reply)
    monkeypatch.setattr(message_event, "show_loading_animation", lambda chat_id: None)
    monkeypatch.setattr(message_event, "get_or_fetch_user_name", lambda event, sid: "小明")
    monkeypatch.setattr(message_event, "format_user_message_for_memory", lambda event, sid, text: f"小明：{text}")
    reply = bot["send"](text_event(MENTION_GROUP, "@G-bot 明天早上八點提醒我開會"))
    assert reply.text == "好喔"
    assert seen["user_input"] == "明天早上八點提醒我開會"
    assert seen["mention_prefix"] == "@G-bot " and seen["chat_id"] == "G_mention"
