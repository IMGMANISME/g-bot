# app/search_modules/google_maps.py
import os
import requests
import random
from app.memory import save_restaurant, get_restaurants_backup
import math

GOOGLE_API_KEY = os.getenv("GOOGLE_MAPS_API_KEY")

def search_restaurants_nearby(lat: float, lng: float, radius=4000, max_results=1, min_price=0, max_price=4, min_rating=3.5):
    # print(f"🔍 搜尋餐廳，位置：{lat},{lng}，半徑：{radius}m，價錢區間：{min_price}~{max_price}")

    url = "https://maps.googleapis.com/maps/api/place/nearbysearch/json"
    params = {
        "location": f"{lat},{lng}",
        "radius": radius,
        "type": "restaurant",
        "opennow": True,
        "language": "zh-TW",
        "key": GOOGLE_API_KEY,
        "minprice": min_price,
        "maxprice": max_price
    }

    try:
        response = requests.get(url, params=params)
        data = response.json()
    except Exception as e:
        print(f"❌ 連線失敗：{e}")
        data = {"status": "API_CONNECTION_ERROR"}

    status = data.get("status", "API_CONNECTION_ERROR")

    # 失敗或超額，從資料庫撈資料
    if status in ["OVER_QUERY_LIMIT", "REQUEST_DENIED", "INVALID_REQUEST", "UNKNOWN_ERROR", "API_CONNECTION_ERROR"]:
        print(f"⚠️ API 錯誤：{status}，改從資料庫撈取備援資料")
        db_results = get_restaurants_backup(lat, lng, radius, min_price, max_price, min_rating, max_results)

        if not db_results:
            return "⚠️ Google Maps API 無法使用，且本地資料庫內也沒有備援餐廳資料。"

        formatted = []
        for place in db_results:
            maps_url = f"https://www.google.com/maps/place/?q=place_id:{place.place_id}"
            formatted.append(
                f"🍽️ {place.name}\n⭐ 評分：{place.rating}\n📍 地址：{place.address}\n🔗 地圖：{maps_url}"
            )
        return "⚠️ 以下是從歷史資料中推薦的餐廳：\n\n" + "\n\n".join(formatted)

    elif status == "ZERO_RESULTS":
        return "❌ 半徑內找不到符合條件的餐廳，再試試別的地點或距離吧～"
    elif status != "OK":
        return f"❌ 餐廳搜尋失敗：{status}"

    all_results = [
        r for r in data.get("results", [])
        if r.get("rating", 0) >= min_rating and min_price <= r.get("price_level", -1) <= max_price
    ]

    if not all_results:
        return "❌ 找不到符合價位與評分的餐廳，試試別的範圍或條件？"

    random.shuffle(all_results)
    results = all_results[:max_results]

    formatted = []
    for place in results:
        # 儲存到資料庫
        save_restaurant(place, lat, lng)

        name = place.get("name")
        address = place.get("vicinity")
        rating = place.get("rating", "N/A")
        maps_url = f"https://www.google.com/maps/place/?q=place_id:{place.get('place_id')}"

        formatted.append(
            f"🍽️ {name}\n⭐ 評分：{rating}\n📍 地址：{address}\n🔗 地圖：{maps_url}"
        )

    return "\n\n".join(formatted)