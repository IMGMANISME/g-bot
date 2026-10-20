# app/tools/base.py
"""工具的共用型別與註冊表。

新增功能時，在 app/tools/ 下新增一個模組，用 @tool 註冊即可：模型會自動知道這個工具，
不用修改對話流程。記得把模組加進 TOOL_MODULES。

    @tool(
        name="get_current_time",
        description="使用者問現在幾點時使用。",
    )
    def get_current_time(args: dict, ctx: ToolContext) -> ToolResult:
        ...
"""
from dataclasses import dataclass, field
from datetime import datetime
from importlib import import_module
from typing import Callable

from google.genai import types

from app.utils.logger import setup_logger

logger = setup_logger("tools")

# 所有工具模組；匯入時會用 @tool 註冊到 TOOL_REGISTRY
TOOL_MODULES = (
    "app.tools.weather",
    "app.tools.reminders",
    "app.tools.restaurants",
    "app.tools.current_time",
)


@dataclass
class QuickReplyItem:
    label: str
    text: str | None = None  # 按下後送出的文字；text 與 data 都是 None 代表「傳送位置」按鈕
    data: str | None = None  # Postback 資料：按下後不送文字給模型，直接由程式處理


@dataclass
class ToolContext:
    chat_id: str  # 提醒、地震等設定存在聊天室底下
    sender_id: str  # 位置、餐廳推薦紀錄跟著個人
    user_text: str
    now: datetime
    mention_prefix: str = ""  # 標記模式下，按鈕文字要加上 @G-bot


@dataclass
class ToolResult:
    data: dict  # 交給模型改寫的結果
    fallback_text: str  # 模型改寫失敗時直接回覆
    attachment: str | None = None  # 附在回覆後面、不經模型改寫的內容（例如餐廳清單與連結）
    quick_replies: list[QuickReplyItem] = field(default_factory=list)


ToolHandler = Callable[[dict, ToolContext], ToolResult]


@dataclass(frozen=True)
class Tool:
    name: str
    description: str  # 給模型看的說明：什麼時候該用這個工具
    parameters: dict | None  # JSON Schema 風格的參數定義（type 用大寫：OBJECT、STRING…）
    handler: ToolHandler

    def declaration(self) -> types.FunctionDeclaration:
        return types.FunctionDeclaration(name=self.name, description=self.description, parameters=self.parameters)


TOOL_REGISTRY: dict[str, Tool] = {}


def tool(name: str, description: str, parameters: dict | None = None) -> Callable[[ToolHandler], ToolHandler]:
    """註冊一個工具。parameters 可以只寫 properties（會自動包成 OBJECT），也可以給完整的 schema。"""
    if parameters is not None and parameters.get("type") != "OBJECT":
        parameters = {"type": "OBJECT", "properties": parameters}

    def register(handler: ToolHandler) -> ToolHandler:
        if name in TOOL_REGISTRY and TOOL_REGISTRY[name].handler is not handler:
            raise ValueError(f"工具名稱重複: {name}")
        TOOL_REGISTRY[name] = Tool(name, description, parameters, handler)
        return handler

    return register


def load_tools() -> dict[str, Tool]:
    for module in TOOL_MODULES:
        import_module(module)
    return TOOL_REGISTRY


def gemini_tools() -> list[types.Tool]:
    """提供給 Gemini 的工具清單"""
    return [types.Tool(function_declarations=[t.declaration() for t in load_tools().values()])]


def execute_tool(name: str, args: dict, ctx: ToolContext) -> ToolResult:
    registered = load_tools().get(name)
    if not registered:
        logger.warning(f"模型要求了不存在的工具: {name}")
        return ToolResult(data={"error": f"沒有 {name} 這個工具"}, fallback_text="這個我還不會做耶，換個方式問我看看？")
    try:
        return registered.handler(args or {}, ctx)
    except Exception as e:
        logger.error(f"工具 {name} 執行失敗: {e}", exc_info=True)
        return ToolResult(data={"error": "工具執行失敗"}, fallback_text="⚠️ 我剛剛處理的時候出了點問題，請再試一次。")
