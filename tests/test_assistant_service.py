import pytest
from google.genai import types

import app.services.assistant_service as assistant
from app.gemini_engine import GeminiUnavailable, ModelTurn
from app.tools.base import QuickReplyItem, ToolResult


@pytest.fixture
def flow(monkeypatch, now):
    """把資料庫、模型與工具都換成假的，記錄每一步"""
    state = {"memory": {}, "calls": [], "plan": None, "rewrite": None,
             "tool_result": ToolResult({"status": "ok"}, "模板回覆")}

    def save_message(memory_id, role, content):
        state["memory"].setdefault(memory_id, []).append({"role": role, "content": content})

    def plan_reply(system, history, tools):
        state["calls"].append(("plan", history[-1]["content"]))
        if isinstance(state["plan"], Exception):
            raise state["plan"]
        return state["plan"]

    def reply_with_tool_result(system, history, tools, function_call, result, model_content=None):
        state["calls"].append(("rewrite", function_call.name, dict(function_call.args or {}), model_content))
        return state["rewrite"]

    def execute_tool(name, args, ctx):
        state["calls"].append(("tool", name, args, ctx.mention_prefix))
        return state["tool_result"]

    monkeypatch.setattr(assistant, "save_message", save_message)
    monkeypatch.setattr(assistant, "get_history", lambda memory_id: list(state["memory"].get(memory_id, [])))
    monkeypatch.setattr(assistant, "plan_reply", plan_reply)
    monkeypatch.setattr(assistant, "reply_with_tool_result", reply_with_tool_result)
    monkeypatch.setattr(assistant, "execute_tool", execute_tool)
    monkeypatch.setattr(assistant, "now_taipei", lambda: now)
    return state


def ask(text, prefix=""):
    return assistant.get_assistant_reply(
        memory_id="M1", chat_id="C1", sender_id="U1", user_input=text, memory_user_input=text,
        user_name="小明", is_multi_user_chat=False, mention_prefix=prefix,
    )


def steps(flow):
    return [call[0] for call in flow["calls"]]


def test_chat_calls_model_once_and_saves(flow):
    flow["plan"] = ModelTurn(text="辛苦了，早點休息吧")
    reply = ask("我今天好累")
    assert reply.text == "辛苦了，早點休息吧" and steps(flow) == ["plan"]
    assert flow["memory"]["M1"] == [{"role": "user", "content": "我今天好累"},
                                    {"role": "assistant", "content": "辛苦了，早點休息吧"}]


def test_model_chosen_tool_is_executed_and_rewritten(flow):
    call = types.FunctionCall(name="create_reminder", args={"datetime": "2026-10-21 08:00", "content": "開會", "repeat_daily": False})
    content = types.Content(role="model", parts=[types.Part(function_call=call)])
    flow["plan"] = ModelTurn(function_call=call, content=content)
    flow["rewrite"] = "好喔，明天 08:00 叫你開會"
    flow["tool_result"] = ToolResult({"status": "created"}, "模板", quick_replies=[QuickReplyItem("取消這個提醒", "取消提醒 1")])

    reply = ask("明天早上八點叫我開會", prefix="@G-bot ")
    assert steps(flow) == ["plan", "tool", "rewrite"]
    assert flow["calls"][1][3] == "@G-bot "  # 標記模式前綴傳給工具
    assert flow["calls"][2][3] is content  # 改寫時附上模型原始回覆
    assert reply.text == "好喔，明天 08:00 叫你開會"
    assert reply.quick_replies[0].label == "取消這個提醒"


def test_fast_path_skips_planning(flow):
    flow["rewrite"] = "台北接下來幾天都不錯"
    reply = ask("台北天氣")
    assert steps(flow) == ["tool", "rewrite"]
    assert flow["calls"][0][1] == "get_weather"
    assert reply.text == "台北接下來幾天都不錯"


def test_rewrite_failure_falls_back_to_template(flow):
    flow["rewrite"] = None
    reply = ask("現在幾點")
    assert reply.text == "模板回覆"
    assert flow["memory"]["M1"][-1] == {"role": "assistant", "content": "模板回覆"}


def test_attachment_is_appended_but_not_saved(flow):
    flow["rewrite"] = "附近有兩間不錯的"
    flow["tool_result"] = ToolResult({"status": "found"}, "模板", attachment="🍽️ 清單")
    reply = ask("吃什麼")
    assert reply.text == "附近有兩間不錯的\n\n🍽️ 清單"
    assert flow["memory"]["M1"][-1]["content"] == "附近有兩間不錯的"


def test_model_failure_reply_is_not_saved(flow):
    flow["plan"] = GeminiUnavailable("⚠️ 額度用完了")
    reply = ask("我今天好累")
    assert reply.text == "⚠️ 額度用完了"
    assert flow["memory"]["M1"] == [{"role": "user", "content": "我今天好累"}]


def test_markdown_is_removed_from_chat(flow):
    flow["plan"] = ModelTurn(text="**重點**是休息")
    assert ask("我好累").text == "重點是休息"
