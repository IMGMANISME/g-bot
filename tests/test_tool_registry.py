import pytest

from app.tools.base import TOOL_REGISTRY, ToolContext, ToolResult, execute_tool, gemini_tools, load_tools, tool

EXPECTED_TOOLS = {"get_weather", "create_reminder", "recommend_restaurants", "get_current_time"}


def test_all_tool_modules_are_registered():
    assert EXPECTED_TOOLS <= set(load_tools())


def test_gemini_declarations_match_registry():
    declarations = gemini_tools()[0].function_declarations
    assert {d.name for d in declarations} == set(load_tools())
    for declaration in declarations:
        assert declaration.description, f"{declaration.name} 缺少說明，模型會不知道什麼時候該用"


def test_parameters_shorthand_is_wrapped_as_object():
    weather = load_tools()["get_weather"]
    assert weather.parameters["type"] == "OBJECT"
    assert set(weather.parameters["properties"]) == {"city", "date", "focus"}
    assert load_tools()["create_reminder"].parameters["required"] == ["datetime", "content", "repeat_daily"]
    assert load_tools()["get_current_time"].parameters is None


@pytest.fixture
def temporary_tool():
    yield
    TOOL_REGISTRY.pop("echo_for_test", None)


def test_new_tool_is_available_to_model_and_executor(temporary_tool, now):
    @tool(name="echo_for_test", description="測試用", parameters={"text": {"type": "STRING"}})
    def echo(args, ctx):
        return ToolResult({"echo": args["text"]}, args["text"])

    assert "echo_for_test" in {d.name for d in gemini_tools()[0].function_declarations}
    result = execute_tool("echo_for_test", {"text": "hi"}, ToolContext("C", "U", "", now))
    assert result.data == {"echo": "hi"}


def test_duplicate_tool_name_is_rejected(temporary_tool):
    @tool(name="echo_for_test", description="第一個")
    def first(args, ctx):
        return ToolResult({}, "")

    with pytest.raises(ValueError, match="工具名稱重複"):
        @tool(name="echo_for_test", description="第二個")
        def second(args, ctx):
            return ToolResult({}, "")
