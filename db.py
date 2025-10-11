from sqlalchemy import create_engine, Column, Integer, String, Float, ForeignKey, UniqueConstraint, DateTime
from sqlalchemy.orm import declarative_base, relationship, sessionmaker
import os, datetime

DB_PATH = os.environ.get("ACPOF_DB_PATH", "data.db")
DB_URL  = os.environ.get("ACPOF_DB_URL")

if DB_URL and DB_URL.startswith("postgresql"):
    engine = create_engine(DB_URL, echo=False, pool_pre_ping=True, pool_size=5, max_overflow=10, future=True)
else:
    engine = create_engine(f"sqlite:///{DB_PATH}", echo=False, future=True)

SessionLocal = sessionmaker(bind=engine, expire_on_commit=False, future=True)
Base = declarative_base()

class Supplier(Base):
    __tablename__ = "suppliers"
    id      = Column(Integer, primary_key=True)
    name    = Column(String, unique=True, nullable=False)
    contact = Column(String, default="")
    phone   = Column(String, default="")
    email   = Column(String, default="")
    notes   = Column(String, default="")
    # relation inverse dans Ingredient
