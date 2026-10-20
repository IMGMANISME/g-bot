import pytest
from google.genai import errors, types

import app.gemini_engine as engine
from app.tools.base import gemini_tools

TOOLS = gemini_tools()

HISTORY = [
    {"role": "user", "content": "嗨"},
    {"role": "assistant", "content": "嗨嗨"},
    {"role": "realtime_info", "content": "舊版存的天氣資料"},  # 舊資料要略過
    {"role": "user", "content": "先問一下"},
    {"role": "user", "content": "高雄明天會下雨嗎"},
]
WEATHER_CALL = types.FunctionCall(name="get_weather", args={"city": "高雄市", "focus": "rain"})


def response(*parts):
    return types.GenerateContentResponse(candidates=[types.Candidate(content=types.Content(role="model", parts=list(parts)))])


def text(value):
    return types.Part.from_text(text=value)


@pytest.fixture
def model(monkeypatch):
    """假的 Gemini client：依序回傳 replies，並記錄每次請求"""
    state = {"replies": [], "requests": []}

    class FakeModels:
        def generate_content(self, model, contents, config):
            state["requests"].append({"contents": contents, "config": config})
            reply = state["replies"].pop(0)
            if isinstance(reply, Exception):
                raise reply
            return reply

    class FakeClient:
        models = FakeModels()

    monkeypatch.setattr(engine, "genai_client", FakeClient())
    monkeypatch.setattr(engine._generate.retry, "sleep", lambda seconds: None)  # 重試不用真的等
    return state


def test_plan_returns_tool_call(model):
    model["replies"].append(response(types.Part(function_call=WEATHER_CALL)))
    turn = engine.plan_reply("系統提示", HISTORY, TOOLS)
    assert turn.function_call.name == "get_weather" and turn.content is not None

    request = model["requests"][0]
    # realtime_info 被略過，連續兩則 user 合併成一則
    assert [(c.role, len(c.parts)) for c in request["contents"]] == [("user", 1), ("model", 1), ("user", 2)]
    config = request["config"]
    assert config.tools == TOOLS
    assert config.automatic_function_calling.disable is True
    assert config.http_options.timeout == engine.PLAN_TIMEOUT_SECONDS * 1000


def test_plan_returns_text(model):
    model["replies"].append(response(text("辛苦了，早點休息")))
    assert engine.plan_reply("s", HISTORY, TOOLS).text == "辛苦了，早點休息"


def test_plan_empty_reply_raises(model):
    model["replies"].append(response(text("")))
    with pytest.raises(engine.GeminiUnavailable):
        engine.plan_reply("s", HISTORY, TOOLS)


@pytest.mark.parametrize("code, expected", [
    (402, engine.QUOTA_ERROR_REPLY),
    (403, engine.AUTH_ERROR_REPLY),
    (401, engine.AUTH_ERROR_REPLY),
    (400, engine.GENERIC_ERROR_REPLY),
])
def test_plan_client_errors_are_not_retried(model, code, expected):
    model["replies"].append(errors.ClientError(code, {"error": {"message": "x"}}))
    with pytest.raises(engine.GeminiUnavailable) as caught:
        engine.plan_reply("s", HISTORY, TOOLS)
    assert caught.value.reply == expected
    assert len(model["requests"]) == 1


def test_plan_retries_rate_limit_once(model):
    model["replies"] += [errors.ClientError(429, {"error": {"message": "x"}}), response(text("哈囉"))]
    assert engine.plan_reply("s", HISTORY, TOOLS).text == "哈囉"
    assert len(model["requests"]) == 2


def test_rewrite_sends_call_and_result(model):
    model_content = types.Content(role="model", parts=[types.Part(function_call=WEATHER_CALL)])
    model["replies"].append(response(text("明天高雄七成會下雨，記得帶傘")))
    reply = engine.reply_with_tool_result("s", HISTORY, TOOLS, WEATHER_CALL, {"rain": 70}, model_content)
    assert reply == "明天高雄七成會下雨，記得帶傘"

    contents = model["requests"][0]["contents"]
    assert contents[-2].role == "model" and contents[-2].parts[0].function_call.name == "get_weather"
    function_response = contents[-1].parts[0].function_response
    assert function_response.name == "get_weather" and function_response.response == {"rain": 70}
    assert model["requests"][0]["config"].http_options.timeout == engine.REWRITE_TIMEOUT_SECONDS * 1000


def test_rewrite_adds_call_for_fast_path(model):
    model["replies"].append(response(text("好喔")))
    engine.reply_with_tool_result("s", HISTORY, TOOLS, types.FunctionCall(name="get_current_time", args={}), {"time": "x"})
    assert model["requests"][0]["contents"][-2].parts[0].function_call.name == "get_current_time"


@pytest.mark.parametrize("replies", [
    [errors.ServerError(503, {"error": {"message": "busy"}}), response(text(""))],
    [response(types.Part(function_call=WEATHER_CALL))],
    [errors.ClientError(402, {"error": {"message": "quota"}})],
])
def test_rewrite_failure_returns_none(model, replies):
    model["replies"] += replies
    assert engine.reply_with_tool_result("s", HISTORY, TOOLS, WEATHER_CALL, {}) is None


@pytest.mark.parametrize("raw, expected", [
    ("<reply>明天會下雨</reply>", "明天會下雨"),
    ("Thought process: check weather\n\n<reply>帶傘喔</reply>", "帶傘喔"),
    ("普通的回答", "普通的回答"),
])
def test_extract_final_reply(raw, expected):
    assert engine._extract_final_reply(raw) == expected


def test_meta_leak_detection():
    assert engine._contains_meta_leak("Constraint check: no emoji")
    assert not engine._contains_meta_leak("明天記得帶傘")
