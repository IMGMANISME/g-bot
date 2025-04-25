#app/search_modules/time.py
from datetime import datetime
import pytz

def get_realtime() -> str:
    tz = pytz.timezone("Asia/Taipei")
    now = datetime.now(tz)

    weekdays = {
        "Monday": "星期一", "Tuesday": "星期二", "Wednesday": "星期三",
        "Thursday": "星期四", "Friday": "星期五", "Saturday": "星期六", "Sunday": "星期日"
    }
    weekday_cn = weekdays[now.strftime("%A")]
    return now.strftime("%Y-%m-%d %H:%M:%S ") + weekday_cn