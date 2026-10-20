"""實測完整對話流程（真的 Gemma，假的資料庫／天氣／餐廳），檢查回覆口吻與事實是否正確。

用法：
    GEMINI_API_KEY=... python scripts/try_assistant.py        # 全部
    GEMINI_API_KEY=... python scripts/try_assistant.py 3 9    # 只跑第 3、9 句

不會寫入資料庫、不會推播 LINE。每句會顯示：走的路徑、用的工具、最後回覆、是否退回模板、耗時。
"""
import os
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

if not os.getenv("GEMINI_API_KEY"):
    sys.exit("請先設定 GEMINI_API_KEY 環境變數")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
# 匯入 app 前先給必要設定的假值（不會真的連線）
os.environ.setdefault("DATABASE_URL", "postgresql://fake:fake@localhost:5432/fake")
os.environ.setdefault("LINE_CHANNEL_ACCESS_TOKEN", "fake")
os.environ.setdefault("CWA_API_KEY", "fake")
os.environ.setdefault("LOG_LEVEL", "WARNING")

import app.repositories.notification_repository as notification_repo  # noqa: E402
import app.search_modules.weather as weather  # noqa: E402
import app.services.assistant_service as assistant  # noqa: E402
import app.services.restaurant_service as restaurant_service  # noqa: E402
import app.tools.reminders as reminder_tools  # noqa: E402
import app.tools.restaurants as restaurant_tools  # noqa: E402
from app.utils.time_utils import now_taipei  # noqa: E402

REQUEST_INTERVAL_SECONDS = 4

# --- 假的對話紀錄（記憶體） ---
memory: dict[str, list[dict]] = {}


def fake_save_message(memory_id, role, content):
    memory.setdefault(memory_id, []).append({"role": role, "content": content})
    del memory[memory_id][:-10]


assistant.save_message = fake_save_message
assistant.get_history = lambda memory_id: list(memory.get(memory_id, []))

# --- 假的提醒資料庫 ---
_next_id = iter(range(1, 1000))


def fake_add_notification(sender_id, message, run_at, repeat_daily, interval_minutes=None, window=None):
    return notification_repo.NotificationRecord(
        next(_next_id), sender_id, message, repeat_daily, run_at, interval_minutes,
        window.start if window else None, window.end if window else None,
    )


reminder_tools.add_scheduled_notification = fake_add_notification
reminder_tools.get_message_quota = lambda: {"type": "limited", "limit": 200, "used": 20}

# --- 假的天氣資料：明天下雨、週五偏冷 ---
NOW = now_taipei()
PLAN = [
    ("多雲時晴", 21, 27, "10"), ("晴時多雲", 20, 23, "0"),
    ("多雲短暫陣雨", 22, 26, "60"), ("陰短暫雨", 21, 23, "70"),
    ("晴時多雲", 23, 31, "10"), ("多雲", 22, 25, "20"),
    ("多雲", 14, 19, "30"), ("陰", 13, 16, "40"),
    ("晴", 18, 26, "0"), ("晴", 15, 18, "0"),
    ("多雲", 19, 25, "20"), ("多雲", 18, 21, "20"),
    ("多雲", 20, 26, "10"), ("多雲", 19, 22, "10"),
]
FIELDS = [("天氣現象", "Weather"), ("最低溫度", "MinTemperature"), ("最高溫度", "MaxTemperature"), ("12小時降雨機率", "ProbabilityOfPrecipitation")]


def fake_forecast(city):
    start = NOW.replace(hour=6, minute=0, second=0, microsecond=0)
    data = {"records": {"Locations": [{"Location": [{"WeatherElement": [
        {"ElementName": name, "Time": [
            {"StartTime": (start + timedelta(hours=12 * i)).isoformat(), "ElementValue": [{key: str(slot[col])}]}
            for i, slot in enumerate(PLAN)
        ]}
        for col, (name, key) in enumerate(FIELDS)
    ]}]}]}}
    return weather.parse_daily_forecast(data)


weather.fetch_daily_forecast = fake_forecast

# --- 假的餐廳：U_noloc 沒有位置，其他人有 ---
FAKE_LIST = (
    "🍽️ 幫你挑了 2 間評價不錯的餐廳（偏好：拉麵）\n\n"
    "1. 🍜 一風堂 信義店\n⭐ 評分：4.3（1520 則）\n💰 價位：$$\n📏 距離：約 350 公尺\n\n"
    "2. 🍜 麵屋武藏\n⭐ 評分：4.1（980 則）\n💰 價位：$$\n📏 距離：約 620 公尺"
)


def fake_recommend(sender_id, query):
    if sender_id == "U_noloc":
        return restaurant_service.RestaurantResult("想找附近好吃的話，先傳你的位置給我喔 📍", [], needs_location=True)
    return restaurant_service.RestaurantResult(FAKE_LIST, ["p1", "p2"])


restaurant_tools.get_restaurant_recommendation = fake_recommend

# --- 記錄每句走了哪條路 ---
trace = {}
_original_execute = assistant.execute_tool
_original_rewrite = assistant.reply_with_tool_result


def traced_execute(name, args, ctx):
    result = _original_execute(name, args, ctx)
    trace.update(tool=name, args=args, fallback=result.fallback_text)
    return result


def traced_rewrite(*args, **kwargs):
    start = time.monotonic()
    text = _original_rewrite(*args, **kwargs)
    trace.update(rewrite_seconds=time.monotonic() - start, rewritten=text)
    return text


assistant.execute_tool = traced_execute
assistant.reply_with_tool_result = traced_rewrite

CASES = [
    # (訊息, 使用者 ID, 檢查重點)
    ("高雄明天會下雨嗎", "U1", "應提到降雨機率約 70% 並提醒帶傘"),
    ("週五新竹會不會冷", "U1", "應提到 13–19 度、偏冷"),
    ("台北天氣", "U1", "應簡短講接下來幾天，提到明天會下雨"),
    ("明天早上八點叫我開會", "U2", "應確認明天 08:00 提醒開會"),
    ("30分鐘後提醒我關火", "U2", f"應確認約 {(NOW + timedelta(minutes=30)):%H:%M} 提醒關火"),
    ("提醒我 繳電費 23:30", "U2", "快速通道；應確認 23:30 提醒繳電費"),
    ("每兩小時提醒我喝水", "U5", "應請使用者確認（還沒建立），後面附設定卡片與「確定建立」按鈕"),
    ("附近有什麼好吃的拉麵", "U3", "應一兩句開場，後面附清單"),
    ("吃什麼", "U_noloc", "應請使用者傳位置"),
    ("現在幾點", "U1", f"應回答約 {NOW:%H:%M}"),
    ("我今天好累", "U4", "一般聊天，不用工具"),
    ("我明天要開會", "U4", "一般聊天，不該建立提醒"),
]


def main():
    print(f"模型：{os.getenv('GEMINI_MODEL', 'gemma-4-26b-a4b-it')}　現在時間：{NOW:%Y-%m-%d %H:%M}　共 {len(CASES)} 句\n")
    selected = {int(arg) for arg in sys.argv[1:] if arg.isdigit()}
    totals = []
    fallbacks = 0
    first = True
    for index, (text, user, expectation) in enumerate(CASES, start=1):
        if selected and index not in selected:
            continue
        if not first:
            time.sleep(REQUEST_INTERVAL_SECONDS)
        first = False
        trace.clear()
        start = time.monotonic()
        try:
            reply = assistant.get_assistant_reply(
                memory_id=user, chat_id=user, sender_id=user, user_input=text,
                memory_user_input=text, user_name="測試者", is_multi_user_chat=False,
            )
        except Exception as e:
            print(f"{index:>2}. ❌ {text}\n    發生錯誤：{type(e).__name__}: {e}\n")
            continue
        elapsed = time.monotonic() - start
        totals.append(elapsed)

        used_fallback = "tool" in trace and not trace.get("rewritten")
        fallbacks += used_fallback
        route = "不用工具" if "tool" not in trace else f"{trace['tool']} {trace['args']}"
        print(f"{index:>2}. {text}　（共 {elapsed:.1f} 秒）")
        print(f"    檢查：{expectation}")
        print(f"    路徑：{route}")
        if used_fallback:
            print("    ⚠️ Gemma 改寫失敗，退回模板")
        print("    回覆：" + reply.text.replace("\n", "\n          "))
        if reply.quick_replies:
            print(f"    按鈕：{[item.label for item in reply.quick_replies]}")
        print()

    print("=" * 50)
    if totals:
        print(f"平均耗時：{sum(totals) / len(totals):.1f} 秒　最慢：{max(totals):.1f} 秒")
    print(f"退回模板：{fallbacks} 次")
    print("請逐句確認：回覆是否像人、內容是否和「檢查」一致（特別是時間與數字）。")


if __name__ == "__main__":
    main()
