"""用真實的 webhook 格式（含簽名）走完事件註冊流程，LINE API 與資料庫換成假的。"""
import base64
import hashlib
import hmac
import json

import pytest
from linebot.v3 import WebhookHandler

import app.handlers.events.location_event as location_event
import app.handlers.events.message_event as message_event
import app.handlers.events.postback_event as postback_event
import app.line_bot as line_bot
import app.repositories.user_repository as user_repository
import app.utils.line_utils as line_utils
import app.views.line_menus as line_menus

SECRET = "test-secret"
USER = {"type": "user", "userId": "U1"}
MENTION_GROUP = {"type": "group", "groupId": "G_mention", "userId": "U2"}


@pytest.fixture
def bot(monkeypatch):
    state = {"replies": [], "locations": [], "states": {"G_mention": "mention"}}

    class FakeMessagingApi:
        def reply_message(self, request):
            state["replies"].extend(request.messages)

        def push_message(self, request, x_line_retry_key=None):
            state["replies"].extend(request.messages)

    class SyncExecutor:
        def submit(self, fn):
            fn()

    monkeypatch.setattr(line_utils, "messaging_api", FakeMessagingApi())
    monkeypatch.setattr(line_bot, "background_executor", SyncExecutor())
    get_state = lambda chat_id: state["states"].get(chat_id, "active")
    for module in (user_repository, location_event, message_event, postback_event, line_menus):
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
    reply = bot["send"](event("follow", USER, follow={"isUnblocked": False}))
    assert "我是 G-Bot" in reply.text and "#幫助" in reply.text
    assert labels(reply) == ["💧 喝水提醒", "台北天氣", "10 分鐘後提醒我", "📍 傳送位置", "幫助"]
    assert type(reply.quick_reply.items[0].action).__name__ == "PostbackAction"
    assert type(reply.quick_reply.items[3].action).__name__ == "LocationAction"


def test_unblock_says_welcome_back(bot):
    reply = bot["send"](event("follow", USER, follow={"isUnblocked": True}))
    assert reply.text.startswith("歡迎回來")


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


def test_group_reply_quotes_the_message(bot):
    reply = bot["send"](text_event(MENTION_GROUP, "@G-bot #狀態"))
    assert reply.quote_token == "q"


def test_one_on_one_reply_does_not_quote(bot):
    reply = bot["send"](text_event(USER, "#狀態"))
    assert reply.quote_token is None


@pytest.fixture
def earthquake_settings(monkeypatch):
    settings = {"enabled": False, "min_magnitude": None}
    monkeypatch.setattr(user_repository, "set_earthquake_subscription", lambda cid, enabled: settings.update(enabled=enabled))
    monkeypatch.setattr(user_repository, "set_earthquake_min_magnitude",
                        lambda cid, magnitude: settings.update(enabled=True, min_magnitude=magnitude))
    monkeypatch.setattr(user_repository, "get_earthquake_settings", lambda cid: dict(settings))
    return settings


def test_turning_earthquake_alerts_on_offers_thresholds(bot, earthquake_settings):
    reply = bot["send"](text_event(USER, "地震通知開"))
    assert earthquake_settings["enabled"] is True
    assert "規模 4.0 以上" in reply.text
    assert button_texts(reply) == ["地震門檻 4.0", "地震門檻 4.5", "地震門檻 5.0", "地震通知關"]


def test_turning_earthquake_alerts_off_offers_undo(bot, earthquake_settings):
    earthquake_settings["enabled"] = True
    reply = bot["send"](text_event(USER, "地震通知關"))
    assert earthquake_settings["enabled"] is False
    assert button_texts(reply) == ["地震通知開"]


def test_setting_threshold_turns_alerts_on(bot, earthquake_settings):
    reply = bot["send"](text_event(USER, "地震門檻 4.5"))
    assert earthquake_settings == {"enabled": True, "min_magnitude": 4.5}
    assert "規模 4.5 以上" in reply.text


def test_welcome_mentions_earthquake_alerts(bot):
    reply = bot["send"](event("follow", USER, follow={"isUnblocked": False}))
    assert "地震通知開" in reply.text


@pytest.fixture
def echo_action():
    from app.tools.base import ACTION_REGISTRY, ToolResult, action

    @action("echo_test")
    def echo(params, ctx):
        return ToolResult({}, f"收到 {params} 來自 {ctx.chat_id}，前綴「{ctx.mention_prefix}」")

    yield
    ACTION_REGISTRY.pop("echo_test", None)


def test_postback_runs_action_without_mention(bot, echo_action):
    payload = event("postback", MENTION_GROUP, postback={"data": "echo_test:42"})
    reply = bot["send"](payload)
    # 標記模式的群組也不用 @G-bot：按鈕直接處理
    assert reply.text == "收到 ['42'] 來自 G_mention，前綴「@G-bot 」"


def test_unknown_postback_is_explained(bot):
    reply = bot["send"](event("postback", USER, postback={"data": "gone:1"}))
    assert "失效" in reply.text


def test_postback_button_is_built_with_display_text():
    from app.tools.base import QuickReplyItem
    from app.views.line_menus import build_reply_message

    message = build_reply_message("確認？", [QuickReplyItem("確定建立", data="reminder_confirm:abc"), QuickReplyItem("改", "改成每1小時")])
    postback, text = [item.action for item in message.quick_reply.items]
    assert type(postback).__name__ == "PostbackAction"
    assert (postback.data, postback.display_text) == ("reminder_confirm:abc", "確定建立")
    assert type(text).__name__ == "MessageAction" and text.text == "改成每1小時"


def test_reminder_list_shows_recurrence(bot, monkeypatch):
    from datetime import time
    from app.repositories.notification_repository import NotificationRecord
    from app.utils.time_utils import now_taipei
    soon = now_taipei().replace(second=0, microsecond=0)
    monkeypatch.setattr(message_event, "get_user_notifications", lambda sid: [
        NotificationRecord(7, "U1", "喝水", False, soon, 120, time(9), time(21)),
    ])
    reply = bot["send"](text_event(USER, "我的提醒"))
    assert "• 編號 7｜每 2 小時（09:00–21:00），下一次今天" in reply.text


@pytest.fixture
def assistant_reply(bot, monkeypatch):
    from app.services.assistant_service import AssistantReply
    monkeypatch.setattr(message_event, "get_assistant_reply", lambda **kwargs: AssistantReply("台北今天晴天"))
    monkeypatch.setattr(message_event, "show_loading_animation", lambda chat_id: None)
    monkeypatch.setattr(message_event, "get_or_fetch_user_name", lambda event, sid: "小明")
    monkeypatch.setattr(message_event, "format_user_message_for_memory", lambda event, sid, text: text)
    return bot


def test_due_reminder_is_attached_to_reply_as_separate_bubble(assistant_reply, monkeypatch):
    from datetime import time
    from app.repositories.notification_repository import NotificationRecord
    from app.utils.time_utils import now_taipei
    water = NotificationRecord(1, "U1", "喝水", False, now_taipei(), 180, time(0), time(0))
    nudged = []
    monkeypatch.setattr(message_event, "due_nudges", lambda chat_id, now: [water] if chat_id == "U1" else [])
    monkeypatch.setattr(message_event, "mark_nudged", lambda record, now: nudged.append(record.id))

    assistant_reply["send"](text_event(USER, "台北天氣"))
    first, second = assistant_reply["replies"]
    assert first.text == "台北今天晴天"
    assert second.text == "⏰ 順便提醒你：喝水"
    assert [b.action.label for b in second.quick_reply.items] == ["喝了 ✅", "30 分鐘後再提醒", "今天不用了"]
    assert nudged == [1]  # 回覆成功後才延後下一次推播


def test_no_nudge_bubble_when_nothing_is_due(assistant_reply, monkeypatch):
    monkeypatch.setattr(message_event, "due_nudges", lambda chat_id, now: [])
    assistant_reply["send"](text_event(USER, "台北天氣"))
    assert [m.text for m in assistant_reply["replies"]] == ["台北今天晴天"]


def test_nudge_lookup_failure_does_not_break_reply(assistant_reply, monkeypatch):
    def broken(chat_id, now):
        raise RuntimeError("db down")
    monkeypatch.setattr(message_event, "due_nudges", broken)
    assistant_reply["send"](text_event(USER, "台北天氣"))
    assert [m.text for m in assistant_reply["replies"]] == ["台北今天晴天"]


def test_menu_has_water_button_only_in_one_on_one(bot):
    reply = bot["send"](text_event(USER, "#選單"))
    assert "💧 喝水提醒" in labels(reply)
    group_reply = bot["send"](text_event({"type": "group", "groupId": "G1", "userId": "U2"}, "#選單"))
    assert "💧 喝水提醒" not in labels(group_reply)


def test_postback_reply_includes_confirmation_card(bot, monkeypatch):
    import app.tools.reminders as reminders
    import app.tools.water as water
    monkeypatch.setattr(water, "get_recurring_notifications", lambda chat_id: [])
    monkeypatch.setattr(reminders, "get_message_quota", lambda: {"type": "none"})
    reply = bot["send"](event("postback", USER, postback={"data": "water_window:0900:2100"}))
    assert "📋 提醒設定（還沒建立）" in reply.text and "頻率：每 3 小時（09:00–21:00）" in reply.text


def test_called_without_mention_answers_once(bot):
    reply = bot["send"](text_event(MENTION_GROUP, "這個機器人到底會幹嘛"))
    assert reply.text.startswith("有人叫我嗎？")
    assert [b.action.label for b in reply.quick_reply.items] == ["我會做什麼", "@G-bot 台北天氣"]
    assert bot["send"](text_event(MENTION_GROUP, "G-bot 你在嗎")) is None  # 10 分鐘內不再回


@pytest.mark.parametrize("text", ["大家晚安", "gbot很好用", "GBOT"])
def test_called_detection(bot, text):
    reply = bot["send"](text_event(MENTION_GROUP, text))
    assert (reply is not None) == ("bot" in text.lower())


def test_silent_mention_group_only_answers_when_mentioned(bot):
    bot["states"]["G_mention"] = "silent_mention"
    assert bot["send"](text_event(MENTION_GROUP, "大家晚安")) is None
    assert "靜音" in bot["send"](text_event(MENTION_GROUP, "@G-bot 在嗎")).text


def test_feature_command_uses_guide(bot):
    reply = bot["send"](text_event(USER, "#功能"))
    assert reply.text.startswith("我可以幫你做這些事")
    assert "☀️ 天氣" in [b.action.label for b in reply.quick_reply.items]
