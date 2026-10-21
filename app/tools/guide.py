# app/tools/guide.py
"""使用說明：所有功能說明的唯一來源。

使用者用自然的說法問「你會做什麼」「提醒怎麼設」時由模型呼叫 explain_features；
「#功能」指令、群組的「有人叫我嗎？」按鈕也都用這裡的內容，新增功能時記得在 FEATURES 加一筆。
"""
from dataclasses import dataclass

from app.tools.base import QuickReplyItem, ToolContext, ToolResult, action, postback_data, tool

EXPLAIN_FEATURES = "explain_features"
GUIDE_ACTION = "guide"


@dataclass(frozen=True)
class Feature:
    key: str
    title: str  # 含 emoji 的名稱
    summary: str  # 一句話說明（總覽用）
    examples: tuple[str, ...]  # 可以直接說的範例（也會變成按鈕）
    details: tuple[str, ...] = ()  # 詳細說明（問到這個功能時才列出）
    private_only: bool = False  # 只能在一對一聊天使用
    group_only: bool = False  # 只在群組有意義


FEATURES = (
    Feature(
        "weather", "☀️ 天氣", "查縣市天氣、會不會下雨、冷不冷",
        ("台北天氣", "高雄明天會下雨嗎", "週末台中冷不冷"),
        ("可以指定日期：今天、明天、後天、週六、下週一、週末", "沒說縣市時會先看臺中市"),
    ),
    Feature(
        "reminder", "⏰ 提醒", "一次性、每天固定時間的提醒",
        ("明天早上八點提醒我開會", "每天晚上十點提醒我吃藥", "我的提醒"),
        (
            "也可以說「30 分鐘後提醒我關火」「下週一下午三點半提醒我繳電費」",
            "說「我現在有哪些提醒」可以查看，「不用再提醒我開會了」或「取消提醒 編號」可以取消",
        ),
    ),
    Feature(
        "recurring", "💧 喝水／週期提醒", "每隔一段時間提醒（像是喝水）",
        ("喝水提醒", "每兩小時提醒我喝水", "我剛喝了水"),
        (
            "建立前會先列出頻率和推播用量，按「確定建立」才生效；沒說時段預設 09:00–21:00",
            "收到提醒可以按「喝了」「30 分鐘後再提醒」「今天不用了」，跟我聊天時也會順便提醒（不花推播額度）",
        ),
        private_only=True,
    ),
    Feature(
        "restaurant", "🍜 找吃的", "推薦附近的餐廳",
        ("附近有什麼好吃的", "吃什麼 便宜", "吃什麼 拉麵"),
        ("要先傳位置給我（聊天室的「+」→「位置資訊」）", "可以加條件：便宜、近一點、遠一點、料理種類、幾間"),
    ),
    Feature(
        "earthquake", "🌍 地震速報", "有感地震馬上通知（預設關閉）",
        ("地震通知開", "地震門檻 4.5", "地震通知關"),
        ("門檻是規模，預設 4.0 以上才通知",),
    ),
    Feature(
        "time", "🕐 時間", "現在幾點、今天幾號",
        ("現在幾點", "今天星期幾"),
    ),
    Feature(
        "settings", "⚙️ 設定", "用說的就能查看或修改設定",
        ("我現在設了什麼", "你先安靜一下", "忘掉剛剛的對話"),
        (
            "安靜後說「可以說話了」我就會回來",
            "改設定後可以按「復原」改回來；清除對話紀錄、取消全部提醒會先問你確定嗎",
            "也可以用指令：#安靜、#說話、我的設定、#清除",
        ),
    ),
    Feature(
        "group", "👥 群組設定", "要我全部都回，或被叫才回",
        ("以後被叫才回", "群組每句都回", "#狀態"),
        (
            "被叫才回（#標記）：只在有人在訊息前面加「@G-bot」時才回覆",
            "每句都回（#都回）：群組裡每則訊息都會回覆",
        ),
        group_only=True,
    ),
    Feature(
        "chat", "💬 聊天", "其他問題直接問我",
        ("幫我想一句生日祝福",),
    ),
)
FEATURE_KEYS = [f.key for f in FEATURES]


def _is_group(chat_id: str) -> bool:
    return chat_id.startswith(("C", "R"))


def _example_button(example: str, prefix: str) -> QuickReplyItem:
    return QuickReplyItem(example[:20], f"{prefix}{example}")


def build_overview(chat_id: str, prefix: str = "") -> ToolResult:
    """功能總覽（依聊天室類型），附各功能的說明按鈕"""
    in_group = _is_group(chat_id)
    features = [f for f in FEATURES if not (f.group_only and not in_group)]
    lines = ["我可以幫你做這些事 👇"]
    for f in features:
        note = "（私訊限定）" if f.private_only and in_group else ""
        lines.append(f"{f.title}{note}：{f.summary}，例如「{f.examples[0]}」")
    if in_group and prefix:
        lines.append("\n在這個群組找我，記得在訊息前面加上「@G-bot」。")
    lines.append("\n想知道某個功能怎麼用，點下面的按鈕或直接問我。")
    return ToolResult(
        {"status": "overview"},
        "\n".join(lines),
        quick_replies=[
            QuickReplyItem(f.title[:20], data=postback_data(GUIDE_ACTION, f.key))
            for f in features if f.key != "chat"
        ],
    )


def build_feature_detail(key: str, chat_id: str, prefix: str = "") -> ToolResult:
    feature = next((f for f in FEATURES if f.key == key), None)
    if feature is None:
        return build_overview(chat_id, prefix)

    in_group = _is_group(chat_id)
    private_only_here = feature.private_only and in_group
    lines = [f"{feature.title}：{feature.summary}"]
    if private_only_here:
        lines.append("⚠️ 這個功能只能私訊設定，在群組裡太常推播會吵到大家。加我好友後私訊我就能用。")
        lines.append("\n私訊我時可以這樣說：")
        lines += [f"• {example}" for example in feature.examples]
    else:
        lines.append("\n可以這樣說：")
        lines += [f"• {prefix}{example}" for example in feature.examples]
    if feature.details:
        lines.append("")
        lines += [f"• {detail}" for detail in feature.details]

    buttons = [] if private_only_here else [_example_button(e, prefix) for e in feature.examples]
    buttons.append(QuickReplyItem("其他功能", data=postback_data(GUIDE_ACTION, "overview")))
    return ToolResult({"status": "detail", "feature": key}, "\n".join(lines), quick_replies=buttons)


@tool(
    name=EXPLAIN_FEATURES,
    description=(
        "說明 G-Bot 有哪些功能、怎麼使用。使用者問你會做什麼、有什麼功能、某個功能怎麼用、"
        "在群組要怎麼叫你，或要求你做做不到的事時使用。"
    ),
    parameters={
        "topic": {
            "type": "STRING",
            "enum": FEATURE_KEYS,
            "description": "使用者問的功能；問全部功能或不確定時留空。"
            "weather 天氣、reminder 提醒、recurring 喝水或週期提醒、restaurant 找餐廳、"
            "earthquake 地震、time 時間、settings 設定、group 群組設定、chat 聊天",
        },
    },
    rewrite=False,
)
def explain_features(args: dict, ctx: ToolContext) -> ToolResult:
    topic = args.get("topic")
    if topic in FEATURE_KEYS:
        return build_feature_detail(topic, ctx.chat_id, ctx.mention_prefix)
    return build_overview(ctx.chat_id, ctx.mention_prefix)


@action(GUIDE_ACTION)
def guide(params: list[str], ctx: ToolContext) -> ToolResult:
    key = params[0] if params else "overview"
    if key == "overview":
        return build_overview(ctx.chat_id, ctx.mention_prefix)
    return build_feature_detail(key, ctx.chat_id, ctx.mention_prefix)
