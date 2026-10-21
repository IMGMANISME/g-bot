"""實測 Gemma 的 Function Calling 能力：用 app 實際註冊的工具，檢查是否選對工具與參數。

用法（金鑰從環境變數讀取，不會印出）：
    GEMINI_API_KEY=... python scripts/try_function_calling.py              # 全部
    GEMINI_API_KEY=... python scripts/try_function_calling.py 1 5 12       # 只跑指定的句子
    TOOL_SET=basic GEMINI_API_KEY=... python scripts/try_function_calling.py  # 只給最早的 4 個工具（比較用）

新增工具或修改工具說明後跑一次，確認模型仍能正確選擇。
"""
import os
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from google import genai
from google.genai import errors, types

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
# 匯入 app 前先給必要設定的假值（只讀取工具定義，不會連資料庫或 LINE）
os.environ.setdefault("DATABASE_URL", "postgresql://fake:fake@localhost:5432/fake")
os.environ.setdefault("LINE_CHANNEL_ACCESS_TOKEN", "fake")
os.environ.setdefault("LOG_LEVEL", "WARNING")

from app.services.reminder_schedule import parse_clock  # noqa: E402
from app.tools.base import gemini_tools  # noqa: E402

MODEL = os.getenv("GEMINI_MODEL", "gemma-4-26b-a4b-it")
TZ = ZoneInfo("Asia/Taipei")
WEEKDAYS = "一二三四五六日"
REQUEST_INTERVAL_SECONDS = 4  # 避免撞到免費方案每分鐘請求上限

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
            elif key in ("window_start", "window_end"):
                ok = parse_clock(got) == parse_clock(want)  # 9:00 與 09:00 視為相同
            elif key == "repeat_daily":
                ok = bool(got) == want  # 沒填視為不重複，程式也是這樣處理
            elif key == "interval_minutes" and got is not None:
                ok = want is not None and int(got) == want
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
         [check_datetime(at(tomorrow, 8)), check_fields(content="開會", repeat_daily=False, interval_minutes=None)]),
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
        # 週期提醒
        ("每兩小時提醒我喝水", "create_reminder", [check_fields(content="喝水", interval_minutes=120)]),
        ("早上九點到下午六點，每小時提醒我起來動一動", "create_reminder",
         [check_fields(interval_minutes=60, window_start="09:00", window_end="18:00")]),
        ("整天每三小時提醒我吃藥", "create_reminder",
         [check_fields(content="吃藥", interval_minutes=180, window_start="00:00", window_end="00:00")]),
        ("每30分鐘提醒我看一下烤箱", "create_reminder", [check_fields(interval_minutes=30)]),
        ("我想要定時提醒我喝水", "start_water_reminder", []),
        # 查詢、回報完成、取消
        ("我現在有哪些提醒", "list_reminders", []),
        ("我剛喝完一杯水了", "mark_reminder_done", [check_fields(content="水")]),
        ("藥已經吃了", "mark_reminder_done", [check_fields(content="藥")]),
        ("不用再提醒我喝水了", "cancel_reminder", [check_fields(content="喝水")]),
        ("把明天開會的提醒刪掉", "cancel_reminder", [check_fields(content="開會")]),
        ("我喜歡喝水", None, []),
        # 使用說明、做不到的事
        ("我不知道怎麼用你", "explain_features", []),
        ("提醒要怎麼設定", "explain_features", [check_fields(topic="reminder")]),
        ("幫我訂明天的高鐵票", ("explain_features", None), []),  # 誠實說做不到也算對
        # 用說的改設定
        ("你先安靜一下", "update_reply_mode", [check_fields(mode="silent")]),
        ("以後在群組被叫才回", "update_reply_mode", [check_fields(mode="mention_only")]),
        ("幫我打開地震速報", "update_earthquake_alert", [check_fields(enabled=True)]),
        ("規模5以上的地震再通知我", "update_earthquake_alert", [check_fields(min_magnitude=5)]),
        ("我現在設了什麼", "show_settings", []),
        ("忘掉剛剛的對話", "clear_conversation", []),
        ("提醒全部取消", "cancel_all_reminders", []),
        ("大家安靜一下，老師要講話了", None, []),
        ("我今天好累", None, []),
        ("我明天要開會", None, []),
        ("你覺得台北好玩嗎", None, []),
        ("昨天下雨好煩", None, []),
        ("幫我想一句生日祝福", None, []),
    ]


SERVER_ERRORS = 0  # 遇到幾次 Google 端的 5xx（重試前也算）


BASIC_TOOLS = {"get_weather", "create_reminder", "recommend_restaurants", "get_current_time"}


def selected_tools() -> list[types.Tool]:
    """TOOL_SET=basic 時只給最早的 4 個工具，用來比較工具數量是否影響錯誤率"""
    tools = gemini_tools()
    if os.getenv("TOOL_SET") != "basic":
        return tools
    return [types.Tool(function_declarations=[d for d in tools[0].function_declarations if d.name in BASIC_TOOLS])]


def call_model(client, text: str, config) -> tuple[object, float]:
    """和正式環境一樣：5xx 重試（這裡最多 2 次）、429 等一分鐘再試"""
    global SERVER_ERRORS
    for attempt in range(3):
        start = time.monotonic()
        try:
            response = client.models.generate_content(model=MODEL, contents=text, config=config)
            return response, time.monotonic() - start
        except errors.ServerError as e:
            SERVER_ERRORS += 1
            if attempt < 2:
                print(f"  遇到 {e.code}（Google 伺服器錯誤），{3 * (attempt + 1)} 秒後重試…")
                time.sleep(3 * (attempt + 1))
                continue
            raise
        except errors.ClientError as e:
            if e.code == 429 and attempt < 2:
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
        tools=selected_tools(),
        automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
        temperature=0.2,
    )
    selected = {int(arg) for arg in sys.argv[1:] if arg.isdigit()}
    cases = [(i, case) for i, case in enumerate(build_cases(now), start=1) if not selected or i in selected]
    tool_names = [d.name for d in selected_tools()[0].function_declarations]
    print(f"模型：{MODEL}　現在時間：{now:%Y-%m-%d %H:%M}（星期{WEEKDAYS[now.weekday()]}）　共 {len(cases)} 句")
    print(f"工具（{len(tool_names)} 個）：{', '.join(tool_names)}\n")

    tool_ok = args_ok = 0
    latencies = []
    for index, (text, expected_tool, checks) in cases:
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

        accepted = expected_tool if isinstance(expected_tool, tuple) else (expected_tool,)
        tool_match = got_tool in accepted
        problems = [p for check in checks for p in [check(args)] if p] if tool_match and calls else []
        tool_ok += tool_match
        args_ok += tool_match and not problems

        mark = "✅" if tool_match and not problems else ("⚠️" if tool_match else "❌")
        print(f"{index:>2}. {mark} {text}　（{elapsed:.1f} 秒）")
        expected_text = " 或 ".join(name or "不用工具" for name in accepted)
        print(f"    預期：{expected_text}　實際：{got_tool or '不用工具'}")
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
    print(f"Google 伺服器錯誤（5xx）：{SERVER_ERRORS} 次（已自動重試）")
    print(f"工具選擇正確：{tool_ok}/{total}")
    print(f"工具與參數都正確：{args_ok}/{total}")
    if latencies:
        print(f"平均耗時：{sum(latencies) / len(latencies):.1f} 秒　最慢：{max(latencies):.1f} 秒")


if __name__ == "__main__":
    main()
