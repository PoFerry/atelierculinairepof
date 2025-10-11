# db.py
from sqlalchemy import (
    create_engine, Column, Integer, String, Float,
    ForeignKey, UniqueConstraint, DateTime
)
from sqlalchemy.orm import declarative_base, relationship, sessionmaker
import os, datetime

# -------------------------------------------------------------------
# CONFIGURATION DE LA BASE DE DONNÉES
# -------------------------------------------------------------------
DB_PATH = os.environ.get("ACPOF_DB_PATH", "data.db")
DB_URL = os.environ.get("ACPOF_DB_URL")

if DB_URL and DB_URL.startswith("postgresql"):
    engine = create_engine(
        DB_URL, echo=False, pool_pre_ping=True,
        pool_size=5, max_overflow=10, future=True
    )
else:
    engine = create_engine(f"sqlite:///{DB_PATH}", echo=False, future=True)

SessionLocal = sessionmaker(bind=engine, expire_on_commit=False, future=True)
Base = declarative_base()


# -------------------------------------------------------------------
# TABLES PRINCIPALES
# -------------------------------------------------------------------

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

    supplier_id = Column(Integer, ForeignKey("suppliers.id"))
    supplier = relationship("Supplier", back_populates="ingredients")

    pack_size = Column(Float, default=0.0)
    pack_unit = Column(String, default="g")
    purchase_price = Column(Float, default=0.0)
    price_per_base_unit = Column(Float, default=0.0)
    base_unit = Column(String, default="g")

    created_at = Column(DateTime, default=datetime.datetime.utcnow)


class Recipe(Base):
    __tablename__ = "recipes"
    id = Column(Integer, primary_key=True)
    name = Column(String, unique=True, nullable=False)
    category = Column(String, default="")
    servings = Column(Integer, default=1)
    instructions = Column(String, default="")

    items = relationship("RecipeItem", back_populates="recipe", cascade="all, delete-orphan")


class RecipeItem(Base):
    __tablename__ = "recipe_items"
    id = Column(Integer, primary_key=True)
    recipe_id = Column(Integer, ForeignKey("recipes.id"), nullable=False)
    ingredient_id = Column(Integer, ForeignKey("ingredients.id"), nullable=False)
    quantity = Column(Float, default=0.0)
    unit = Column(String, default="g")

    recipe = relationship("Recipe", back_populates="items")
    ingredient = relationship("Ingredient")

    __table_args__ = (UniqueConstraint("recipe_id", "ingredient_id", name="uix_recipe_ingredient"),)


# -------------------------------------------------------------------
# INVENTAIRE ET STOCKS
# -------------------------------------------------------------------
class StockMovement(Base):
    __tablename__ = "stock_movements"
    id = Column(Integer, primary_key=True)
    ingredient_id = Column(Integer, ForeignKey("ingredients.id"), nullable=False)
    qty = Column(Float, default=0.0)
    unit = Column(String, default="g")
    movement_type = Column(String, default="entrée")
    notes = Column(String, default="")
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

    ingredient = relationship("Ingredient")


# -------------------------------------------------------------------
# MENUS
# -------------------------------------------------------------------
class Menu(Base):
    __tablename__ = "menus"
    id = Column(Integer, primary_key=True)
    name = Column(String, unique=True, nullable=False)
    notes = Column(String, default="")

    items = relationship(
        "MenuItem",
        back_populates="menu",
        cascade="all, delete-orphan",
        passive_deletes=False,
    )


class MenuItem(Base):
    __tablename__ = "menu_items"
    id = Column(Integer, primary_key=True)
    menu_id = Column(Integer, ForeignKey("menus.id"), nullable=False)
    recipe_id = Column(Integer, ForeignKey("recipes.id"), nullable=False)
    batches = Column(Float, default=1.0)

    menu = relationship("Menu", back_populates="items")
    recipe = relationship("Recipe")

    __table_args__ = (UniqueConstraint("menu_id", "recipe_id", name="uix_menu_recipe"),)


# -------------------------------------------------------------------
# INITIALISATION DE LA BD
# -------------------------------------------------------------------
def init_db():
    Base.metadata.create_all(bind=engine)
