# app/tools/definitions.py
"""提供給 Gemma 的工具定義（Function Calling）"""
from google.genai import types

GET_WEATHER = "get_weather"
CREATE_REMINDER = "create_reminder"
RECOMMEND_RESTAURANTS = "recommend_restaurants"
GET_CURRENT_TIME = "get_current_time"

TOOLS = [types.Tool(function_declarations=[
    types.FunctionDeclaration(
        name=GET_WEATHER,
        description="查詢台灣縣市的天氣預報。使用者詢問天氣、會不會下雨、要不要帶傘、冷不冷、溫度時使用。",
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
        name=CREATE_REMINDER,
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
        name=RECOMMEND_RESTAURANTS,
        description="推薦使用者附近的餐廳。使用者想找東西吃、問吃什麼、要餐廳推薦時使用。",
        parameters={
            "type": "OBJECT",
            "properties": {
                "price": {"type": "STRING", "enum": ["cheap", "medium", "expensive", "any"], "description": "價位"},
                "cuisine": {"type": "STRING", "description": "料理類型，例如 拉麵、火鍋；沒指定時留空"},
                "max_distance_m": {"type": "INTEGER", "description": "最遠距離（公尺）；沒指定時留空"},
                "count": {"type": "INTEGER", "description": "要推薦幾間（1 到 5）；沒指定時留空"},
            },
        },
    ),
    types.FunctionDeclaration(
        name=GET_CURRENT_TIME,
        description="取得現在的日期、時間與星期。使用者問現在幾點、今天幾號、星期幾時使用。",
    ),
])]
