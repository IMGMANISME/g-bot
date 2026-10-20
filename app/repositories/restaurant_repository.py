import math
from dataclasses import dataclass
from typing import Optional, Set

from app.database import SessionLocal
from app.models.restaurant import Restaurant


@dataclass(frozen=True)
class RestaurantRecord:
    place_id: str
    name: str
    address: str | None
    rating: float | None
    price_level: int | None
    lat: float
    lng: float


def _to_record(restaurant: Restaurant) -> RestaurantRecord:
    return RestaurantRecord(
        place_id=restaurant.place_id,
        name=restaurant.name,
        address=restaurant.address,
        rating=restaurant.rating,
        price_level=restaurant.price_level,
        lat=restaurant.lat,
        lng=restaurant.lng,
    )


def save_restaurant(place: dict, lat: float, lng: float):
    with SessionLocal() as db:
        place_id = place.get("place_id")
        if not place_id:
            return

        geometry = place.get("geometry", {}).get("location", {})
        place_lat = geometry.get("lat") if geometry.get("lat") is not None else lat
        place_lng = geometry.get("lng") if geometry.get("lng") is not None else lng

        try:
            rating_value = float(place["rating"]) if place.get("rating") is not None else None
        except (TypeError, ValueError):
            rating_value = None

        existing = db.query(Restaurant).filter_by(place_id=place_id).first()
        if existing:
            existing.name = place.get("name") or existing.name
            existing.address = place.get("vicinity") or existing.address
            existing.rating = rating_value if rating_value is not None else existing.rating
            existing.price_level = place.get("price_level")
            existing.lat = float(place_lat)
            existing.lng = float(place_lng)
            db.commit()
            return

        restaurant = Restaurant(
            place_id=place_id,
            name=place.get("name"),
            address=place.get("vicinity"),
            rating=rating_value,
            price_level=place.get("price_level"),
            lat=float(place_lat),
            lng=float(place_lng),
        )
        db.add(restaurant)
        db.commit()

def get_restaurants_backup(
    lat: float,
    lng: float,
    radius=4000,
    min_price=0,
    max_price=4,
    min_rating=3.5,
    limit=5,
    exclude_place_ids: Optional[Set[str]] = None
):
    with SessionLocal() as db:
        lat_diff = radius / 111000
        lng_diff = radius / (111000 * abs(math.cos(math.radians(lat))) + 0.00001)

        query = (
            db.query(Restaurant)
            .filter(Restaurant.lat.between(lat - lat_diff, lat + lat_diff))
            .filter(Restaurant.lng.between(lng - lng_diff, lng + lng_diff))
            .filter(Restaurant.rating >= min_rating)
            .filter(Restaurant.price_level >= min_price, Restaurant.price_level <= max_price)
        )
        if exclude_place_ids:
            query = query.filter(~Restaurant.place_id.in_(list(exclude_place_ids)))

        results = query.all()

        def distance_key(place: Restaurant) -> float:
            place_lat, place_lng = place.lat, place.lng
            dlat = math.radians(place_lat - lat)
            dlng = math.radians(place_lng - lng)
            a = (
                math.sin(dlat / 2) ** 2
                + math.cos(math.radians(lat))
                * math.cos(math.radians(place_lat))
                * math.sin(dlng / 2) ** 2
            )
            c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
            return 6371000 * c

        results.sort(key=lambda place: (distance_key(place), -(place.rating or 0)))
        return [_to_record(place) for place in results[:limit]]
