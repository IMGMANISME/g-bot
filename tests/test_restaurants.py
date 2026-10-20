import pytest

import app.search_modules.google_maps as gm
from app.repositories.restaurant_repository import RestaurantRecord
from app.services.restaurant_service import build_restaurant_query

LAT, LNG = 25.0330, 121.5654


@pytest.mark.parametrize("text, radius", [
    ("附近有什麼好吃的", 1500),
    ("吃什麼 近一點", 500),
    ("吃什麼 遠一點", 2500),
    ("2公里內的火鍋", 2000),
    ("800公尺內", 800),
])
def test_query_radius(text, radius):
    assert build_restaurant_query(text)["radius"] == radius


@pytest.mark.parametrize("text, price", [
    ("吃什麼 便宜", (0, 1, True)),
    ("普通的就好", (2, 2, True)),
    ("想吃貴的", (3, 4, True)),
    ("吃什麼", (0, 4, False)),
])
def test_query_price_from_text(text, price):
    q = build_restaurant_query(text)
    assert (q["min_price"], q["max_price"], q["strict_price"]) == price


def test_model_args_override_text():
    q = build_restaurant_query("吃什麼 便宜", price="expensive", cuisine="火鍋", max_distance_m=50000, count=9)
    assert (q["min_price"], q["max_price"], q["keyword"], q["radius"], q["max_results"]) == (3, 4, "火鍋", 12000, 5)


def test_cuisine_from_text():
    assert build_restaurant_query("吃什麼 拉麵")["keyword"] == "拉麵"


@pytest.mark.parametrize("level, shown", [(None, "未提供"), (0, "$"), (1, "$"), (2, "$$"), (3, "$$$"), (4, "$$$$")])
def test_price_display_matches_google_maps(level, shown):
    assert gm._format_price(level) == shown


# --- Places API (New) ---

class FakeResponse:
    def __init__(self, status_code, data):
        self.status_code = status_code
        self._data = data

    def json(self):
        return self._data


def place(pid, name, dlat, rating=4.5, count=100, price=None):
    p = {"id": pid, "displayName": {"text": name}, "shortFormattedAddress": f"{name}地址",
         "location": {"latitude": LAT + dlat, "longitude": LNG}, "rating": rating, "userRatingCount": count}
    if price:
        p["priceLevel"] = price
    return p


@pytest.fixture
def places_api(monkeypatch):
    """依序回傳排好的回應，並記錄送出的請求"""
    state = {"sent": [], "queue": [], "backup": []}

    def fake_post(url, json, headers, timeout):
        state["sent"].append({"url": url, "body": json, "headers": headers})
        return state["queue"].pop(0)

    monkeypatch.setattr(gm.requests, "post", fake_post)
    monkeypatch.setattr(gm, "GOOGLE_API_KEY", "test-maps-key")
    monkeypatch.setattr(gm, "save_restaurant", lambda *a, **k: None)
    monkeypatch.setattr(gm, "get_restaurants_backup", lambda *a, **k: state["backup"])
    return state


def test_request_format(places_api):
    places_api["queue"].append(FakeResponse(200, {"places": []}))
    gm._fetch_nearby(LAT, LNG, 800, 0, 1, True, "拉麵")
    sent = places_api["sent"][0]
    assert sent["url"] == "https://places.googleapis.com/v1/places:searchText"
    assert sent["headers"]["X-Goog-Api-Key"] == "test-maps-key"
    assert " " not in sent["headers"]["X-Goog-FieldMask"] and "places.rating" in sent["headers"]["X-Goog-FieldMask"]
    body = sent["body"]
    assert (body["textQuery"], body["includedType"], body["languageCode"], body["openNow"]) == ("拉麵", "restaurant", "zh-TW", True)
    assert body["priceLevels"] == ["PRICE_LEVEL_INEXPENSIVE"]
    assert body["locationBias"]["circle"]["radius"] == 800.0


@pytest.mark.parametrize("prices, expected", [
    ((0, 4), None),
    ((2, 2), ["PRICE_LEVEL_MODERATE"]),
    ((3, 4), ["PRICE_LEVEL_EXPENSIVE", "PRICE_LEVEL_VERY_EXPENSIVE"]),
])
def test_price_levels(places_api, prices, expected):
    places_api["queue"].append(FakeResponse(200, {"places": []}))
    gm._fetch_nearby(LAT, LNG, 800, *prices, False, None)
    body = places_api["sent"][0]["body"]
    assert body.get("priceLevels") == expected
    assert "openNow" not in body and body["textQuery"] == "餐廳"


def test_results_are_converted_and_filtered_by_radius(places_api):
    places_api["queue"].append(FakeResponse(200, {"places": [
        place("near", "近的拉麵", 0.002, price="PRICE_LEVEL_INEXPENSIVE"),
        place("far", "太遠的拉麵", 0.02),
        {"id": "nolocation", "displayName": {"text": "沒座標"}},
    ]}))
    status, results = gm._fetch_nearby(LAT, LNG, 800, 0, 1, True, "拉麵")
    assert status == "OK" and [r["place_id"] for r in results] == ["near"]
    assert results[0]["name"] == "近的拉麵" and results[0]["vicinity"] == "近的拉麵地址" and results[0]["price_level"] == 1


def test_search_widens_until_found(places_api):
    places_api["queue"] += [
        FakeResponse(200, {"places": []}),
        FakeResponse(200, {"places": [place("a", "拉麵一號", 0.003, 4.4, 1200, "PRICE_LEVEL_MODERATE")]}),
    ]
    text, ids = gm.search_restaurants_nearby(LAT, LNG, radius=800, max_results=2, keyword="拉麵")
    assert ids == ["a"]
    assert places_api["sent"][1]["body"]["locationBias"]["circle"]["radius"] == 1280.0
    assert "⭐ 評分：4.4（1200 則）" in text and "💰 價位：$$" in text and "place_id:a" in text


def test_permission_error_without_backup(places_api):
    places_api["queue"].append(FakeResponse(403, {"error": {"status": "PERMISSION_DENIED", "message": "not enabled"}}))
    text, ids = gm.search_restaurants_nearby(LAT, LNG, radius=800)
    assert ids == [] and "暫時不可用" in text


def test_quota_error_uses_backup(places_api):
    places_api["backup"] = [RestaurantRecord("old1", "以前存的店", "某地址", 4.2, 1, LAT, LNG)]
    places_api["queue"].append(FakeResponse(429, {"error": {"status": "RESOURCE_EXHAUSTED"}}))
    text, ids = gm.search_restaurants_nearby(LAT, LNG, radius=800)
    assert ids == ["old1"] and "歷史資料" in text


def test_connection_error(monkeypatch):
    def boom(*a, **k):
        raise gm.requests.ConnectionError("down")

    monkeypatch.setattr(gm.requests, "post", boom)
    assert gm._fetch_nearby(LAT, LNG, 800, 0, 4, False, None) == ("API_CONNECTION_ERROR", [])
