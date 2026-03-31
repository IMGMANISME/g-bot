import math
from sqlalchemy import func
from app.database import SessionLocal
from app.models.restaurant import Restaurant

def save_restaurant(place: dict, lat: float, lng: float):
    with SessionLocal() as db:
        if not place.get("place_id"):
            return
        existing = db.query(Restaurant).filter_by(place_id=place["place_id"]).first()
        if not existing:
            restaurant = Restaurant(
                place_id=place["place_id"],
                name=place.get("name"),
                address=place.get("vicinity"),
                rating=place.get("rating"),
                price_level=place.get("price_level"),
                lat=str(lat),
                lng=str(lng),
            )
            db.add(restaurant)
            db.commit()

def get_restaurants_backup(lat: float, lng: float, radius=4000, min_price=0, max_price=4, min_rating=3.5, limit=5):
    with SessionLocal() as db:
        lat_diff = radius / 111000
        lng_diff = radius / (111000 * abs(math.cos(math.radians(lat))) + 0.00001)
        results = db.query(Restaurant)\
            .filter(Restaurant.lat.between(str(lat - lat_diff), str(lat + lat_diff)))\
            .filter(Restaurant.lng.between(str(lng - lng_diff), str(lng + lng_diff)))\
            .filter(Restaurant.rating >= min_rating)\
            .filter(Restaurant.price_level >= min_price, Restaurant.price_level <= max_price)\
            .order_by(func.random())\
            .limit(limit)\
            .all()
        return results
