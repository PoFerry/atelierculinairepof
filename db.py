from __future__ import annotations
from sqlalchemy import create_engine, Column, Integer, String, Float, ForeignKey, UniqueConstraint, DateTime
from sqlalchemy.orm import declarative_base, relationship, sessionmaker
import os, datetime

DB_PATH = os.environ.get("ACPOF_DB_PATH", "data.db")
engine = create_engine(f"sqlite:///{DB_PATH}", echo=False, future=True)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False, future=True)
Base = declarative_base()

class Supplier(Base):
    __tablename__ = "suppliers"
    id = Column(Integer, primary_key=True)
    name = Column(String, unique=True, nullable=False)
    contact = Column(String, default="")
    phone = Column(String, default="")
    email = Column(String, default="")
    notes = Column(String, default="")
    ingredients = relationship("Ingredient", back_populates="supplier")

class Ingredient(Base):
    __tablename__ = "ingredients"
    id = Column(Integer, primary_key=True)
    name = Column(String, unique=True, nullable=False)
    category = Column(String, default="Autre")
    base_unit = Column(String, default="g")  # 'g'|'ml'|'unit'
    pack_size = Column(Float, nullable=False)
    pack_unit = Column(String, nullable=False)
    purchase_price = Column(Float, nullable=False)
    price_per_base_unit = Column(Float, nullable=False)
    supplier_id = Column(Integer, ForeignKey("suppliers.id"), nullable=True)
    supplier = relationship("Supplier", back_populates="ingredients")

class Recipe(Base):
    __tablename__ = "recipes"
    id = Column(Integer, primary_key=True)
    name = Column(String, unique=True, nullable=False)
    category = Column(String, default="Général")
    servings = Column(Integer, default=1)
    items = relationship("RecipeItem", back_populates="recipe", cascade="all, delete-orphan")

class RecipeItem(Base):
    __tablename__ = "recipe_items"
    id = Column(Integer, primary_key=True)
    recipe_id = Column(Integer, ForeignKey("recipes.id"), nullable=False)
    ingredient_id = Column(Integer, ForeignKey("ingredients.id"), nullable=False)
    quantity = Column(Float, nullable=False)
    unit = Column(String, nullable=False)
    recipe = relationship("Recipe", back_populates="items")
    ingredient = relationship("Ingredient")
    __table_args__ = (UniqueConstraint("recipe_id", "ingredient_id", name="uq_recipe_ingredient"),)

class Menu(Base):
    __tablename__ = "menus"
    id = Column(Integer, primary_key=True)
    name = Column(String, unique=True, nullable=False)
    items = relationship("MenuItem", back_populates="menu", cascade="all, delete-orphan")

class MenuItem(Base):
    __tablename__ = "menu_items"
    id = Column(Integer, primary_key=True)
    menu_id = Column(Integer, ForeignKey("menus.id"), nullable=False)
    recipe_id = Column(Integer, ForeignKey("recipes.id"), nullable=False)
    batches = Column(Float, default=1.0)
    menu = relationship("Menu", back_populates="items")
    recipe = relationship("Recipe")

class StockMovement(Base):
    __tablename__ = "stock_movements"
    id = Column(Integer, primary_key=True)
    ingredient_id = Column(Integer, ForeignKey("ingredients.id"), nullable=False)
    quantity_base = Column(Float, nullable=False)  # +in / -out in base unit
    movement_type = Column(String, nullable=False)  # 'in'|'out'|'adjust'
    unit_cost = Column(Float, default=0.0)
    note = Column(String, default="")
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

def init_db():
    Base.metadata.create_all(bind=engine)
