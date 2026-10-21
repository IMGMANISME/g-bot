# app/tools/settings.py
"""用自然的說法改設定：回覆模式、地震通知、查看設定、清除對話紀錄、刪除全部提醒。

「#安靜」「#標記」等指令仍保留當作捷徑。改設定後附「復原」按鈕；刪掉就回不來的動作先確認。
"""
import re

from app.config import config
from app.repositories.message_repository import clear_history
from app.repositories.notification_repository import delete_all_notifications_for_user, get_user_notifications
from app.repositories.user_repository import (
    get_earthquake_settings,
    get_user_state,
    set_earthquake_min_magnitude,
    set_earthquake_subscription,
    set_user_state,
)
from app.tools.base import QuickReplyItem, ToolContext, ToolResult, action, postback_data, tool

UPDATE_REPLY_MODE = "update_reply_mode"
UPDATE_EARTHQUAKE_ALERT = "update_earthquake_alert"
SHOW_SETTINGS = "show_settings"
CLEAR_CONVERSATION = "clear_conversation"
CANCEL_ALL_REMINDERS = "cancel_all_reminders"

RESTORE_MODE = "settings_restore_mode"
CONFIRM_CLEAR = "settings_clear_confirm"
CONFIRM_CANCEL_ALL = "reminder_cancel_all_confirm"
NEVER_MIND = "settings_never_mind"

MODE_NAMES = {
    "active": "所有訊息都回",
    "silent": "靜音",
    "mention": "只在被標記時回",
    "silent_mention": "靜音（標記模式）",
}


def _is_group(chat_id: str) -> bool:
    return chat_id.startswith(("C", "R"))


def settings_text(chat_id: str) -> str:
    """目前設定（「我的設定」指令與 show_settings 工具共用）"""
    earthquake = get_earthquake_settings(chat_id)
    min_magnitude = earthquake["min_magnitude"] or config.EARTHQUAKE_MIN_MAGNITUDE
    reminders = get_user_notifications(chat_id)
    return (
        "目前設定：\n"
        f"回覆模式：{MODE_NAMES.get(get_user_state(chat_id), '所有訊息都回')}\n"
        f"地震通知：{'開' if earthquake['enabled'] else '關'}（規模 {min_magnitude} 以上）\n"
        f"提醒：{len(reminders)} 個"
    )


# --- 回覆模式 ---

# 靜音時不會把訊息交給模型，這些說法要直接辨識
RESUME_PATTERN = re.compile(
    r"^(?:你)?(?:可以|能)?(?:說話|講話|回話|回覆|回我)(?:了|吧)?$"
    r"|^(?:恢復|開始)(?:回覆|說話|講話)$|^解除靜音$|^不用(?:再)?安靜了?$|^回來吧?$"
)


def is_resume_request(text: str) -> bool:
    return bool(RESUME_PATTERN.match((text or "").strip(" 。!！~～")))

def _next_mode(current: str, mode: str) -> str:
    mention = "mention" in current
    return {
        "silent": "silent_mention" if mention else "silent",
        "resume": "mention" if mention else "active",
        "mention_only": "silent_mention" if "silent" in current else "mention",
        "reply_all": "silent" if "silent" in current else "active",
    }[mode]


def change_mode(mode: str, ctx: ToolContext) -> ToolResult:
    current = get_user_state(ctx.chat_id)
    if mode in ("mention_only", "reply_all") and not _is_group(ctx.chat_id):
        return ToolResult({"status": "not_needed"}, "一對一聊天我本來就每句都會回，這個設定是給群組用的喔。")

    new = _next_mode(current, mode)
    if new == current:
        return ToolResult({"status": "unchanged"}, f"目前已經是「{MODE_NAMES[new]}」了。")

    set_user_state(ctx.chat_id, new)
    texts = {
        "silent": "⏸️ 好，我先安靜。想讓我回來時說「可以說話了」或輸入「#說話」。",
        "resume": "▶️ 我回來了！",
        "mention_only": "📌 好，之後在訊息前面加「@G-bot」我才會回。",
        "reply_all": "✅ 好，群組裡每則訊息我都會回。",
    }
    return ToolResult(
        {"status": "changed", "mode": MODE_NAMES[new]},
        texts[mode],
        quick_replies=[QuickReplyItem("復原", data=postback_data(RESTORE_MODE, current))],
    )


@tool(
    name=UPDATE_REPLY_MODE,
    description=(
        "改變 G-Bot 的回覆方式。只有使用者明確要你改變行為時才用（例如「你先安靜一下」「可以說話了」"
        "「以後在群組被叫才回」「群組每句都回」）；別人之間的對話（例如「大家安靜一下」）不要用。"
    ),
    parameters={
        "mode": {
            "type": "STRING",
            "enum": ["silent", "resume", "mention_only", "reply_all"],
            "description": "silent 先不要回覆、resume 恢復回覆、mention_only 群組只在被標記時回、reply_all 群組每則都回",
        },
    },
    rewrite=False,
)
def update_reply_mode(args: dict, ctx: ToolContext) -> ToolResult:
    mode = args.get("mode")
    if mode not in ("silent", "resume", "mention_only", "reply_all"):
        return ToolResult({"status": "need_clarification"}, "要我怎麼回覆呢？可以說「先安靜」「可以說話了」，群組還可以說「被叫才回」或「每句都回」。")
    return change_mode(mode, ctx)


@action(RESTORE_MODE)
def restore_mode(params: list[str], ctx: ToolContext) -> ToolResult:
    previous = params[0] if params and params[0] in MODE_NAMES else "active"
    set_user_state(ctx.chat_id, previous)
    return ToolResult({}, f"↩️ 已經改回「{MODE_NAMES[previous]}」。")


# --- 地震通知 ---

@tool(
    name=UPDATE_EARTHQUAKE_ALERT,
    description="開啟、關閉地震速報，或調整通知的規模門檻（例如「幫我打開地震速報」「規模 5 以上再通知我」「不要再推地震了」）。",
    parameters={
        "enabled": {"type": "BOOLEAN", "description": "開啟填 true、關閉填 false；只調門檻時留空"},
        "min_magnitude": {"type": "NUMBER", "description": "通知的最低規模（0 到 10）；沒說就留空"},
    },
    rewrite=False,
)
def update_earthquake_alert(args: dict, ctx: ToolContext) -> ToolResult:
    magnitude = args.get("min_magnitude")
    enabled = args.get("enabled")
    if magnitude is not None:
        try:
            magnitude = float(magnitude)
        except (TypeError, ValueError):
            magnitude = -1
        if not 0 <= magnitude <= 10:
            return ToolResult({"status": "need_clarification"}, "地震門檻請設定 0 到 10 之間的規模，常用的是 4 到 5。")
        set_earthquake_min_magnitude(ctx.chat_id, magnitude)  # 設定門檻也會開啟通知
        return ToolResult({"status": "changed"}, f"🌍 好，規模 {magnitude:g} 以上的地震會通知你（地震通知已開啟）。")
    if enabled is None:
        return ToolResult({"status": "need_clarification"}, f"{settings_text(ctx.chat_id)}\n\n要開啟、關閉，還是調整門檻呢？")

    set_earthquake_subscription(ctx.chat_id, bool(enabled))
    if enabled:
        min_magnitude = get_earthquake_settings(ctx.chat_id)["min_magnitude"] or config.EARTHQUAKE_MIN_MAGNITUDE
        return ToolResult({"status": "changed"}, f"🌍 地震通知已開啟，規模 {min_magnitude:g} 以上的地震會馬上通知你。")
    return ToolResult({"status": "changed"}, "地震通知已關閉，之後不會再推播地震消息。",
                      quick_replies=[QuickReplyItem("重新開啟", f"{ctx.mention_prefix}地震通知開")])


# --- 查看設定 ---

@tool(
    name=SHOW_SETTINGS,
    description="顯示目前的設定：回覆模式、地震通知、提醒數量。使用者問「我現在設了什麼」「目前設定」時使用。",
    rewrite=False,
)
def show_settings(args: dict, ctx: ToolContext) -> ToolResult:
    return ToolResult({"status": "shown"}, settings_text(ctx.chat_id))


# --- 刪掉就回不來的動作：先確認 ---

def _confirm(question: str, confirm_action: str) -> ToolResult:
    return ToolResult(
        {"status": "needs_confirmation"},
        question,
        quick_replies=[
            QuickReplyItem("確定", data=postback_data(confirm_action)),
            QuickReplyItem("算了", data=postback_data(NEVER_MIND)),
        ],
    )


@tool(
    name=CLEAR_CONVERSATION,
    description=(
        "清除你記得的對話內容（例如「忘掉剛剛的對話」「清除聊天紀錄」「我們重新開始」）。"
        "直接呼叫即可：工具會自己顯示「確定／算了」按鈕讓使用者確認，你不用先用文字問。"
    ),
    rewrite=False,
)
def clear_conversation(args: dict, ctx: ToolContext) -> ToolResult:
    return _confirm("要清除我們的對話紀錄嗎？清除後我就不記得之前聊過什麼了。", CONFIRM_CLEAR)


@action(CONFIRM_CLEAR)
def confirm_clear(params: list[str], ctx: ToolContext) -> ToolResult:
    clear_history(ctx.memory_id or ctx.chat_id)
    return ToolResult({}, "🧹 好，對話紀錄已清除，我們重新開始吧！")


@tool(
    name=CANCEL_ALL_REMINDERS,
    description=(
        "取消這個聊天室的所有提醒（例如「提醒全部取消」「把我的提醒都刪掉」）。"
        "直接呼叫即可：工具會自己顯示「確定／算了」按鈕讓使用者確認，你不用先用文字問。"
    ),
    rewrite=False,
)
def cancel_all_reminders(args: dict, ctx: ToolContext) -> ToolResult:
    count = len(get_user_notifications(ctx.chat_id))
    if not count:
        return ToolResult({"status": "empty"}, "📭 你目前沒有任何提醒。")
    return _confirm(f"要取消全部 {count} 個提醒嗎？取消後就不會再提醒了。", CONFIRM_CANCEL_ALL)


@action(CONFIRM_CANCEL_ALL)
def confirm_cancel_all(params: list[str], ctx: ToolContext) -> ToolResult:
    count = delete_all_notifications_for_user(ctx.chat_id)
    return ToolResult({}, f"🗑️ 好，已取消 {count} 個提醒。")


@action(NEVER_MIND)
def never_mind(params: list[str], ctx: ToolContext) -> ToolResult:
    return ToolResult({}, "好，那就不動。")
