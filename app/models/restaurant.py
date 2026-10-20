from sqlalchemy import Column, String, Integer, DateTime, Float
from datetime import datetime
from app.models.base import Base

class Restaurant(Base):
    __tablename__ = "restaurants"
    place_id = Column(String, primary_key=True)
    name = Column(String, nullable=False)
    address = Column(String)
    rating = Column(Float)
    price_level = Column(Integer)
    lat = Column(Float, nullable=False)
    lng = Column(Float, nullable=False)
    saved_at = Column(DateTime, default=datetime.utcnow)
