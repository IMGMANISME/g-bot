import re
from dataclasses import dataclass

from app.config import config
from app.repositories.user_repository import get_user_location
from app.search_modules.google_maps import search_restaurants_nearby
from app.utils.cache import global_cache


RECENT_RESTAURANT_CACHE_TTL = 60 * 60 * 2
RECENT_RESTAURANT_MAX_IDS = 20


def _recent_restaurant_cache_key(sender_id: str) -> str:
    return f"restaurant_recent:{sender_id}"


def _get_recent_restaurant_ids(sender_id: str) -> list[str]:
    cached = global_cache.get(_recent_restaurant_cache_key(sender_id))
    if not isinstance(cached, list):
        return []
    return [pid for pid in cached if isinstance(pid, str) and pid.strip()]


def _update_recent_restaurant_ids(sender_id: str, recommended_ids: list[str]):
    if not recommended_ids:
        return

    recent = _get_recent_restaurant_ids(sender_id)
    for place_id in recommended_ids:
        if place_id in recent:
            recent.remove(place_id)
        recent.append(place_id)

    if len(recent) > RECENT_RESTAURANT_MAX_IDS:
        recent = recent[-RECENT_RESTAURANT_MAX_IDS:]

    global_cache.set(
        _recent_restaurant_cache_key(sender_id),
        recent,
        ttl=RECENT_RESTAURANT_CACHE_TTL,
    )


def _parse_restaurant_query(user_input: str) -> dict:
    lowered = user_input.lower()

    strict_price = False
    if "便宜" in lowered:
        min_price, max_price = 0, 1
        strict_price = True
    elif "普通" in lowered:
        min_price, max_price = 2, 2
        strict_price = True
    elif "貴" in lowered:
        min_price, max_price = 3, 4
        strict_price = True
    else:
        min_price, max_price = 0, 4

    # 「附近」是口語的找吃的，不代表要縮小範圍；明確說「近一點」才用小半徑
    if "近一點" in lowered:
        radius = config.NEAR_RADIUS
    elif "遠一點" in lowered:
        radius = config.FAR_RADIUS
    else:
        km_match = re.search(r"(\d+(?:\.\d+)?)\s*(公里|km)", lowered)
        meter_match = re.search(r"(\d+)\s*(公尺|米|m)", lowered)
        if km_match:
            radius = int(float(km_match.group(1)) * 1000)
        elif meter_match:
            radius = int(meter_match.group(1))
        else:
            radius = config.DEFAULT_SEARCH_RADIUS

    count_match = re.search(r"(\d+)\s*(間|家)", lowered)
    max_results = int(count_match.group(1)) if count_match else 3

    min_rating = 3.5
    if "高評分" in lowered or "高分" in lowered:
        min_rating = 4.2
    rating_match = re.search(r"評分\s*(\d(?:\.\d)?)\s*(?:以上)?", lowered)
    if rating_match:
        min_rating = max(1.0, min(5.0, float(rating_match.group(1))))

    cuisine_keyword = None
    cuisine_hints = {
        "日式": "日式料理",
        "壽司": "壽司",
        "拉麵": "拉麵",
        "韓式": "韓式料理",
        "火鍋": "火鍋",
        "燒肉": "燒肉",
        "早午餐": "早午餐",
        "咖啡": "咖啡廳",
        "牛排": "牛排",
        "義式": "義式料理",
        "美式": "美式餐廳",
        "甜點": "甜點",
        "素食": "素食",
    }
    for hint, keyword in cuisine_hints.items():
        if hint in lowered:
            cuisine_keyword = keyword
            break

    return {
        "radius": max(300, min(radius, 12000)),
        "max_results": max(1, min(max_results, 5)),
        "min_price": min_price,
        "max_price": max_price,
        "min_rating": min_rating,
        "keyword": cuisine_keyword,
        "strict_price": strict_price,
    }


PRICE_RANGES = {
    # (min_price, max_price, strict_price)
    "cheap": (0, 1, True),
    "medium": (2, 2, True),
    "expensive": (3, 4, True),
    "any": (0, 4, False),
}


@dataclass(frozen=True)
class RestaurantResult:
    text: str  # 餐廳清單或錯誤訊息，可直接回覆
    place_ids: list[str]
    needs_location: bool = False


def build_restaurant_query(
    user_input: str,
    *,
    price: str | None = None,
    cuisine: str | None = None,
    max_distance_m: int | None = None,
    count: int | None = None,
) -> dict:
    """從原句解析條件，再用模型給的參數覆蓋。"""
    query = _parse_restaurant_query(user_input)
    if price in PRICE_RANGES:
        query["min_price"], query["max_price"], query["strict_price"] = PRICE_RANGES[price]
    if cuisine and cuisine.strip():
        query["keyword"] = cuisine.strip()
    if max_distance_m:
        query["radius"] = max(300, min(int(max_distance_m), 12000))
    if count:
        query["max_results"] = max(1, min(int(count), 5))
    return query


def get_restaurant_recommendation(sender_id: str, query: dict) -> RestaurantResult:
    latlng = get_user_location(sender_id)
    if not latlng:
        return RestaurantResult("想找附近好吃的話，先傳你的位置給我喔 📍", [], needs_location=True)

    recent_place_ids = set(_get_recent_restaurant_ids(sender_id))
    result, recommended_place_ids = search_restaurants_nearby(
        latlng[0],
        latlng[1],
        **query,
        exclude_place_ids=recent_place_ids,
    )
    _update_recent_restaurant_ids(sender_id, recommended_place_ids)
    return RestaurantResult(result, recommended_place_ids)
