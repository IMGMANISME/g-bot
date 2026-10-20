"""實測 Gemma 的 Function Calling 能力（階段 1 評估用，不影響線上服務）。

用法（金鑰從環境變數讀取，不會印出）：
    GEMINI_API_KEY=... python scripts/try_function_calling.py

檢查項目：是否選對工具、參數是否正確、每則花費時間。
"""
import os
import sys
import time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from google import genai
from google.genai import errors, types

MODEL = os.getenv("GEMINI_MODEL", "gemma-4-26b-a4b-it")
TZ = ZoneInfo("Asia/Taipei")
WEEKDAYS = "一二三四五六日"
REQUEST_INTERVAL_SECONDS = 4  # 避免撞到免費方案每分鐘請求上限

TOOLS = types.Tool(function_declarations=[
    types.FunctionDeclaration(
        name="get_weather",
        description="查詢台灣縣市的天氣預報。使用者詢問天氣、會不會下雨、冷不冷、溫度時使用。",
        parameters={
            "type": "OBJECT",
            "properties": {
                "city": {"type": "STRING", "description": "縣市全名，例如 臺北市、高雄市、花蓮縣。使用者沒提到時留空"},
                "date": {"type": "STRING", "description": "要查詢的日期，格式 YYYY-MM-DD；沒有指定日期時留空"},
                "focus": {
                    "type": "STRING",
                    "enum": ["rain", "temperature", "general"],
                    "description": "使用者最關心的面向：rain 降雨、temperature 冷熱溫度、general 一般",
                },
            },
        },
    ),
    types.FunctionDeclaration(
        name="create_reminder",
        description=(
            "建立提醒。只有在使用者明確要求「提醒我」「叫我」「記得通知我」之類的請求時才使用；"
            "單純陳述行程（例如「我明天要開會」）不要使用。"
        ),
        parameters={
            "type": "OBJECT",
            "properties": {
                "datetime": {"type": "STRING", "description": "提醒時間，格式 YYYY-MM-DD HH:MM（台北時間）"},
                "content": {"type": "STRING", "description": "提醒內容，例如 開會、吃藥"},
                "repeat_daily": {"type": "BOOLEAN", "description": "是否每天重複"},
            },
            "required": ["datetime", "content", "repeat_daily"],
        },
    ),
    types.FunctionDeclaration(
        name="recommend_restaurants",
        description="推薦使用者附近的餐廳。使用者想找東西吃、問吃什麼、要餐廳推薦時使用。",
        parameters={
            "type": "OBJECT",
            "properties": {
                "price": {"type": "STRING", "enum": ["cheap", "medium", "expensive", "any"], "description": "價位"},
                "cuisine": {"type": "STRING", "description": "料理類型，例如 拉麵、火鍋；沒指定時留空"},
                "max_distance_m": {"type": "INTEGER", "description": "最遠距離（公尺）；沒指定時留空"},
            },
        },
    ),
    types.FunctionDeclaration(
        name="get_current_time",
        description="取得現在的日期、時間與星期。使用者問現在幾點、今天幾號、星期幾時使用。",
    ),
])


def build_system_instruction(now: datetime) -> str:
    return (
        "你是 LINE 聊天機器人 G-Bot，用繁體中文台灣用語回覆。\n"
        f"現在時間是 {now:%Y-%m-%d %H:%M}（星期{WEEKDAYS[now.weekday()]}，台北時間）。\n"
        "需要查天氣、建立提醒、推薦餐廳或查時間時，呼叫對應的工具；其他情況直接用文字回覆。\n"
        "換算「明天」「下週一」「30 分鐘後」等時間時，以上面的現在時間為準。"
    )


def norm_city(value: str | None) -> str:
    return (value or "").replace("台", "臺").removesuffix("市").removesuffix("縣")


def check_datetime(expected: datetime, tolerance_minutes: int = 0):
    def check(args: dict) -> str | None:
        try:
            got = datetime.strptime(args.get("datetime", ""), "%Y-%m-%d %H:%M").replace(tzinfo=TZ)
        except ValueError:
            return f"時間格式錯誤：{args.get('datetime')!r}"
        if abs((got - expected).total_seconds()) > tolerance_minutes * 60:
            return f"時間應為 {expected:%Y-%m-%d %H:%M}，實際 {got:%Y-%m-%d %H:%M}"
        return None
    return check


def check_fields(**expected):
    def check(args: dict) -> str | None:
        problems = []
        for key, want in expected.items():
            got = args.get(key)
            if key == "city":
                ok = norm_city(got) == norm_city(want)
            elif key == "content":
                ok = want in str(got or "")
            else:
                ok = got == want
            if not ok:
                problems.append(f"{key} 應為 {want!r}，實際 {got!r}")
        return "；".join(problems) or None
    return check


def build_cases(now: datetime) -> list[tuple[str, str | None, list]]:
    today = now.date()
    tomorrow = today + timedelta(days=1)
    day_after = today + timedelta(days=2)
    next_monday = today + timedelta(days=(7 - today.weekday()) or 7)

    def at(day, hour, minute=0):
        return datetime(day.year, day.month, day.day, hour, minute, tzinfo=TZ)

    tonight_10 = at(today, 22) if now < at(today, 22) else at(tomorrow, 22)

    return [
        # (訊息, 預期工具（None 代表不該用工具）, 參數檢查)
        ("明天早上八點叫我開會", "create_reminder",
         [check_datetime(at(tomorrow, 8)), check_fields(content="開會", repeat_daily=False)]),
        ("30分鐘後提醒我關火", "create_reminder",
         [check_datetime(now + timedelta(minutes=30), tolerance_minutes=2), check_fields(content="關火")]),
        ("每天晚上十點提醒我吃藥", "create_reminder",
         [check_datetime(tonight_10), check_fields(content="吃藥", repeat_daily=True)]),
        ("下週一下午三點半提醒我繳電費", "create_reminder",
         [check_datetime(at(next_monday, 15, 30)), check_fields(content="電費")]),
        ("高雄明天會下雨嗎", "get_weather",
         [check_fields(city="高雄市", date=tomorrow.isoformat(), focus="rain")]),
        ("台北現在天氣怎樣", "get_weather", [check_fields(city="臺北市")]),
        ("週末台中冷不冷", "get_weather", [check_fields(city="臺中市", focus="temperature")]),
        ("花蓮後天天氣如何", "get_weather", [check_fields(city="花蓮縣", date=day_after.isoformat())]),
        ("附近有什麼便宜的拉麵", "recommend_restaurants", [check_fields(price="cheap", cuisine="拉麵")]),
        ("晚餐不知道要吃什麼", "recommend_restaurants", []),
        ("現在幾點", "get_current_time", []),
        ("我今天好累", None, []),
        ("我明天要開會", None, []),
        ("你覺得台北好玩嗎", None, []),
        ("昨天下雨好煩", None, []),
        ("幫我想一句生日祝福", None, []),
    ]


def call_model(client, text: str, config) -> tuple[object, float]:
    for attempt in range(2):
        start = time.monotonic()
        try:
            response = client.models.generate_content(model=MODEL, contents=text, config=config)
            return response, time.monotonic() - start
        except errors.ClientError as e:
            if e.code == 429 and attempt == 0:
                print("  遇到 429（每分鐘上限），等 60 秒後重試…")
                time.sleep(60)
                continue
            raise


def main():
    if not os.getenv("GEMINI_API_KEY"):
        sys.exit("請先設定 GEMINI_API_KEY 環境變數")

    client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
    now = datetime.now(TZ)
    config = types.GenerateContentConfig(
        system_instruction=build_system_instruction(now),
        tools=[TOOLS],
        automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
        temperature=0.2,
    )
    cases = build_cases(now)
    print(f"模型：{MODEL}　現在時間：{now:%Y-%m-%d %H:%M}（星期{WEEKDAYS[now.weekday()]}）　共 {len(cases)} 句\n")

    tool_ok = args_ok = 0
    latencies = []
    for index, (text, expected_tool, checks) in enumerate(cases, start=1):
        if index > 1:
            time.sleep(REQUEST_INTERVAL_SECONDS)
        try:
            response, elapsed = call_model(client, text, config)
        except Exception as e:
            print(f"{index:>2}. ❌ {text}\n    呼叫失敗：{type(e).__name__}: {str(e)[:200]}\n")
            continue
        latencies.append(elapsed)

        calls = response.function_calls or []
        got_tool = calls[0].name if calls else None
        args = dict(calls[0].args or {}) if calls else {}

        tool_match = got_tool == expected_tool
        problems = [p for check in checks for p in [check(args)] if p] if tool_match and calls else []
        tool_ok += tool_match
        args_ok += tool_match and not problems

        mark = "✅" if tool_match and not problems else ("⚠️" if tool_match else "❌")
        print(f"{index:>2}. {mark} {text}　（{elapsed:.1f} 秒）")
        print(f"    預期：{expected_tool or '不用工具'}　實際：{got_tool or '不用工具'}")
        if calls:
            print(f"    參數：{args}")
        else:
            reply = (response.text or "").strip().replace("\n", " ")
            print(f"    回覆：{reply[:80] or '（空白）'}")
        for problem in problems:
            print(f"    問題：{problem}")
        print()

    total = len(cases)
    print("=" * 50)
    print(f"工具選擇正確：{tool_ok}/{total}")
    print(f"工具與參數都正確：{args_ok}/{total}")
    if latencies:
        print(f"平均耗時：{sum(latencies) / len(latencies):.1f} 秒　最慢：{max(latencies):.1f} 秒")


if __name__ == "__main__":
    main()
