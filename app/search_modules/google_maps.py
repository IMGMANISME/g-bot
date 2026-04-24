# app/search_modules/google_maps.py
import math
import os
from typing import Optional, Set, Tuple

import requests

from app.repositories.restaurant_repository import get_restaurants_backup, save_restaurant
from app.utils.logger import setup_logger

logger = setup_logger("google_maps")

GOOGLE_API_KEY = os.getenv("GOOGLE_MAPS_API_KEY")
GOOGLE_PLACES_URL = "https://maps.googleapis.com/maps/api/place/nearbysearch/json"
API_TIMEOUT_SECONDS = 8
FATAL_API_STATUSES = {
    "OVER_QUERY_LIMIT",
    "REQUEST_DENIED",
    "INVALID_REQUEST",
    "UNKNOWN_ERROR",
    "API_CONNECTION_ERROR",
}


def _haversine_meters(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    radius = 6371000
    dlat = math.radians(lat2 - lat1)
    dlng = math.radians(lng2 - lng1)

    a = (
        math.sin(dlat / 2) ** 2
        + math.cos(math.radians(lat1))
        * math.cos(math.radians(lat2))
        * math.sin(dlng / 2) ** 2
    )
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return radius * c


def _format_price(price_level: Optional[int]) -> str:
    if price_level is None:
        return "未提供"
    return "$" * (price_level + 1)


def _format_distance(distance_m: Optional[float]) -> str:
    if distance_m is None:
        return "未知"
    if distance_m < 1000:
        return f"{int(distance_m)} 公尺"
    return f"{distance_m / 1000:.1f} 公里"


def _safe_float(value) -> Optional[float]:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _fetch_nearby(
    lat: float,
    lng: float,
    radius: int,
    min_price: int,
    max_price: int,
    open_now: bool,
    keyword: Optional[str],
) -> Tuple[str, list]:
    params = {
        "location": f"{lat},{lng}",
        "radius": radius,
        "type": "restaurant",
        "language": "zh-TW",
        "key": GOOGLE_API_KEY,
        "minprice": min_price,
        "maxprice": max_price,
    }
    if open_now:
        params["opennow"] = True
    if keyword:
        params["keyword"] = keyword

    try:
        response = requests.get(GOOGLE_PLACES_URL, params=params, timeout=API_TIMEOUT_SECONDS)
        response.raise_for_status()
        payload = response.json()
    except requests.RequestException as e:
        logger.warning(f"Google Places 連線失敗: {e}")
        return "API_CONNECTION_ERROR", []
    except Exception as e:
        logger.warning(f"Google Places 回應解析失敗: {e}")
        return "API_CONNECTION_ERROR", []

    status = payload.get("status", "UNKNOWN_ERROR")
    return status, payload.get("results", [])


def _rank_results(
    places: list,
    center_lat: float,
    center_lng: float,
    min_price: int,
    max_price: int,
    min_rating: float,
    strict_price: bool = False,
    exclude_place_ids: Optional[Set[str]] = None,
) -> list:
    exclude_place_ids = exclude_place_ids or set()
    ranked = []
    for place in places:
        place_id = place.get("place_id")
        if place_id and place_id in exclude_place_ids:
            continue

        location = place.get("geometry", {}).get("location", {})
        place_lat = _safe_float(location.get("lat"))
        place_lng = _safe_float(location.get("lng"))
        if place_lat is None or place_lng is None:
            continue

        rating = _safe_float(place.get("rating")) or 0
        if rating < min_rating:
            continue

        price_level = place.get("price_level")
        if strict_price and not isinstance(price_level, int):
            continue
        if isinstance(price_level, int) and not (min_price <= price_level <= max_price):
            continue

        distance_m = _haversine_meters(center_lat, center_lng, place_lat, place_lng)
        review_count = int(place.get("user_ratings_total", 0) or 0)

        # 兼顧評分、評論量與距離，避免只看評分導致推薦過遠
        score = (
            rating * 1.8
            + min(math.log1p(review_count), 6) * 0.35
            - (distance_m / 1000) * 1.1
        )
        if isinstance(price_level, int):
            mid_price = (min_price + max_price) / 2
            score -= abs(price_level - mid_price) * 0.15

        ranked.append(
            {
                "place": place,
                "distance_m": distance_m,
                "score": score,
                "review_count": review_count,
            }
        )

    ranked.sort(key=lambda item: item["score"], reverse=True)
    return ranked


def _build_live_message(items: list, keyword: Optional[str]) -> str:
    header = f"🍽️ 幫你挑了 {len(items)} 間評價不錯的餐廳"
    if keyword:
        header += f"（偏好：{keyword}）"

    lines = [header]
    for idx, item in enumerate(items, start=1):
        place = item["place"]
        place_id = place.get("place_id")
        maps_url = f"https://www.google.com/maps/place/?q=place_id:{place_id}"

        rating = place.get("rating")
        rating_text = f"{rating}" if rating is not None else "N/A"
        if item["review_count"] > 0:
            rating_text += f"（{item['review_count']} 則）"

        lines.append(
            (
                f"\n{idx}. 🍜 {place.get('name', '未命名餐廳')}\n"
                f"⭐ 評分：{rating_text}\n"
                f"💰 價位：{_format_price(place.get('price_level'))}\n"
                f"📏 距離：約 {_format_distance(item['distance_m'])}\n"
                f"📍 地址：{place.get('vicinity', '未提供')}\n"
                f"🔗 地圖：{maps_url}"
            )
        )

    return "\n".join(lines)


def _build_backup_message(backup_results: list) -> str:
    lines = ["⚠️ Google Maps 暫時不可用，先用歷史資料推薦："]
    for idx, place in enumerate(backup_results, start=1):
        maps_url = f"https://www.google.com/maps/place/?q=place_id:{place.place_id}"
        lines.append(
            (
                f"\n{idx}. 🍜 {place.name}\n"
                f"⭐ 評分：{place.rating if place.rating is not None else 'N/A'}\n"
                f"💰 價位：{_format_price(place.price_level)}\n"
                f"📍 地址：{place.address}\n"
                f"🔗 地圖：{maps_url}"
            )
        )
    return "\n".join(lines)


def search_restaurants_nearby(
    lat: float,
    lng: float,
    radius: int = 4000,
    max_results: int = 3,
    min_price: int = 0,
    max_price: int = 4,
    min_rating: float = 3.5,
    keyword: Optional[str] = None,
    strict_price: bool = False,
    exclude_place_ids: Optional[Set[str]] = None,
) -> Tuple[str, list[str]]:
    exclude_place_ids = exclude_place_ids or set()

    if not GOOGLE_API_KEY:
        logger.warning("GOOGLE_MAPS_API_KEY 未設定，改用資料庫備援")
        backup = get_restaurants_backup(
            lat,
            lng,
            radius,
            min_price,
            max_price,
            min_rating,
            max_results,
            exclude_place_ids=exclude_place_ids,
        )
        if backup:
            backup_ids = [place.place_id for place in backup if place.place_id]
            return _build_backup_message(backup), backup_ids
        return "⚠️ 目前無法使用餐廳推薦，請稍後再試。", []

    search_plans = [
        {
            "radius": radius,
            "open_now": True,
            "min_price": min_price,
            "max_price": max_price,
            "min_rating": min_rating,
            "keyword": keyword,
        },
        {
            "radius": min(int(radius * 1.6), 12000),
            "open_now": True,
            "min_price": min_price,
            "max_price": max_price,
            "min_rating": max(3.0, min_rating - 0.4),
            "keyword": keyword,
        },
        {
            "radius": min(int(radius * 2.0), 12000),
            "open_now": False,
            "min_price": min_price if strict_price else 0,
            "max_price": max_price if strict_price else 4,
            "min_rating": max(3.0, min_rating - 0.5),
            "keyword": keyword,
        },
    ]
    if keyword:
        search_plans.append(
            {
                "radius": min(int(radius * 2.0), 12000),
                "open_now": False,
                "min_price": min_price,
                "max_price": max_price,
                "min_rating": max(3.0, min_rating - 0.5),
                "keyword": None,
            }
        )

    for plan in search_plans:
        status, results = _fetch_nearby(
            lat=lat,
            lng=lng,
            radius=plan["radius"],
            min_price=plan["min_price"],
            max_price=plan["max_price"],
            open_now=plan["open_now"],
            keyword=plan["keyword"],
        )

        if status in FATAL_API_STATUSES:
            logger.warning(f"Google Places 狀態 {status}，切換資料庫備援")
            backup = get_restaurants_backup(
                lat,
                lng,
                radius,
                min_price,
                max_price,
                min_rating,
                max_results,
                exclude_place_ids=exclude_place_ids,
            )
            if backup:
                backup_ids = [place.place_id for place in backup if place.place_id]
                return _build_backup_message(backup), backup_ids
            return "⚠️ Google Maps 暫時不可用，且目前找不到可用的備援餐廳。", []

        if status not in {"OK", "ZERO_RESULTS"}:
            logger.warning(f"Google Places 回傳異常狀態: {status}")
            continue

        ranked = _rank_results(
            places=results,
            center_lat=lat,
            center_lng=lng,
            min_price=plan["min_price"],
            max_price=plan["max_price"],
            min_rating=plan["min_rating"],
            strict_price=strict_price,
            exclude_place_ids=exclude_place_ids,
        )
        if not ranked:
            continue

        selected = ranked[: max(1, min(max_results, 5))]
        for item in selected:
            save_restaurant(item["place"], lat, lng)
        selected_ids = [
            item["place"].get("place_id")
            for item in selected
            if item["place"].get("place_id")
        ]
        return _build_live_message(selected, plan["keyword"]), selected_ids

    backup = get_restaurants_backup(
        lat,
        lng,
        radius,
        min_price,
        max_price,
        min_rating,
        max_results,
        exclude_place_ids=exclude_place_ids,
    )
    if backup:
        backup_ids = [place.place_id for place in backup if place.place_id]
        return _build_backup_message(backup), backup_ids

    return "❌ 這次找不到符合條件的餐廳，試試放寬條件（像是距離或價位）再問我一次。", []
