"""使用說明：功能總覽、各功能說明、依聊天室類型調整"""
import pytest

from app.tools.base import ToolContext, execute_tool, run_action
from app.tools.guide import FEATURES, build_feature_detail, build_overview
from app.tools.rules import match_fast_path


def ctx(now, chat_id="U1", prefix=""):
    return ToolContext(chat_id=chat_id, sender_id="U1", user_text="", now=now, mention_prefix=prefix)


@pytest.mark.parametrize("text", ["你會做什麼", "有什麼功能？", "怎麼用", "你可以幹嘛", "G-bot 怎麼用", "使用說明", "你是誰"])
def test_help_questions_use_fast_path(now, text):
    assert match_fast_path(text, now) == ("explain_features", {})


@pytest.mark.parametrize("text", ["我不知道怎麼用你", "怎麼用 LINE 傳照片", "台北天氣"])
def test_other_questions_are_not_help(now, text):
    assert (match_fast_path(text, now) or ("",))[0] != "explain_features"


def test_overview_in_private_chat():
    result = build_overview("U1")
    assert "💧 喝水／週期提醒：" in result.fallback_text  # 私訊可以用，沒有「私訊限定」
    assert "群組設定" not in result.fallback_text and "@G-bot" not in result.fallback_text
    assert all(item.data.startswith("guide:") for item in result.quick_replies)


def test_overview_in_mention_mode_group():
    result = build_overview("C1", "@G-bot ")
    assert "💧 喝水／週期提醒（私訊限定）" in result.fallback_text
    assert "👥 群組設定" in result.fallback_text
    assert "記得在訊息前面加上「@G-bot」" in result.fallback_text


def test_detail_with_example_buttons():
    result = build_feature_detail("weather", "C1", "@G-bot ")
    assert "• @G-bot 台北天氣" in result.fallback_text
    assert [b.text for b in result.quick_replies[:3]] == ["@G-bot 台北天氣", "@G-bot 高雄明天會下雨嗎", "@G-bot 週末台中冷不冷"]
    assert result.quick_replies[-1].label == "其他功能"


def test_private_only_feature_in_group_explains_and_has_no_examples_to_tap():
    result = build_feature_detail("recurring", "C1", "@G-bot ")
    assert "只能私訊設定" in result.fallback_text
    assert "私訊我時可以這樣說：\n• 喝水提醒" in result.fallback_text  # 私訊不用加 @G-bot
    assert [b.label for b in result.quick_replies] == ["其他功能"]


def test_tool_with_topic_and_without(now):
    assert execute_tool("explain_features", {"topic": "earthquake"}, ctx(now)).data == {"status": "detail", "feature": "earthquake"}
    assert execute_tool("explain_features", {}, ctx(now)).data == {"status": "overview"}
    assert execute_tool("explain_features", {"topic": "unknown"}, ctx(now)).data == {"status": "overview"}


def test_guide_buttons(now):
    assert run_action("guide:reminder", ctx(now)).data["feature"] == "reminder"
    assert run_action("guide:overview", ctx(now)).data["status"] == "overview"


def test_every_feature_fits_line_limits():
    for feature in FEATURES:
        assert feature.examples, feature.key
        for chat_id in ("U1", "C1"):
            result = build_feature_detail(feature.key, chat_id, "@G-bot ")
            assert all(len(b.label) <= 20 for b in result.quick_replies), feature.key
            assert len(result.quick_replies) <= 13


def test_guide_skips_model_rewrite():
    from app.tools.base import should_rewrite
    assert not should_rewrite("explain_features")
