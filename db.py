# db.py
from __future__ import annotations
import os
import datetime
from sqlalchemy import (
    create_engine, Column, Integer, String, Float, ForeignKey, UniqueConstraint, DateTime
)
from sqlalchemy.orm import declarative_base, relationship, sessionmaker

# -------------------------------------------------------------------
#  CONFIG BDD : SQLite par défaut (Supabase/PG plus tard via ACPOF_DB_URL)
# -------------------------------------------------------------------
DB_PATH = os.environ.get("ACPOF_DB_PATH", "data.db")
DB_URL  = os.environ.get("ACPOF_DB_URL")  # laisser vide pour SQLite

if DB_URL and DB_URL.startswith("postgresql"):
    engine = create_engine(
        DB_URL,
        echo=False,
        pool_pre_ping=True,
        pool_size=5,
        max_overflow=10,
        future=True,
    )
else:
    engine = create_engine(
        f"sqlite:///{DB_PATH}",
        echo=False,
        future=True,
    )

SessionLocal = sessionmaker(bind=engine, expire_on_commit=False, future=True)
Base = declarative_base()

# -------------------------------------------------------------------
#  MODÈLES
# -------------------------------------------------------------------
class Supplier(Base):
    __tablename__ = "suppliers"

    id      = Column(Integer, primary_key=True)
    name    = Column(String, unique=True, nullable=False)
    contact = Column(String, default="")
    phone   = Column(String, default="")
    email   = Column(String, default="")
    notes   = Column(String, default="")

    # Relation inverse vers Ingredient
    ingredients = relationship(
        "Ingredient",
        back_populates="supplier",
        cascade="all, save-update",
        passive_deletes=False,
    )


class Ingredient(Base):
    __tablename__ = "ingredients"

    id                   = Column(Integer, primary_key=True)
    name                 = Column(String, unique=True, nullable=False)
    category             = Column(String, default="Autre")
    base_unit            = Column(String, default="g")  # g | ml | unit
    pack_size            = Column(Float, nullable=False)
    pack_unit            = Column(String, nullable=False)
    purchase_price       = Column(Float, nullable=False)
    price_per_base_unit  = Column(Float, nullable=False)

    supplier_id          = Column(Integer, ForeignKey("suppliers.id"), nullable=True)
    supplier             = relationship(
        "Supplier",
        back_populates="ingredients",
    )


class Recipe(Base):
    __tablename__ = "recipes"

    id           = Column(Integer, primary_key=True)
    name         = Column(String, unique=True, nullable=False)
    category     = Column(String, default="Général")
    servings     = Column(Integer, default=1)
    instructions = Column(String, default="")

    items        = relationship(
        "RecipeItem",
        back_populates="recipe",
        cascade="all, delete-orphan",
        passive_deletes=False,
    )


class RecipeItem(Base):
    __tablename__ = "recipe_items"

    id            = Column(Integer, primary_key=True)
    recipe_id     = Column(Integer, ForeignKey("recipes.id"), nullable=False)
    ingredient_id = Column(Integer, ForeignKey("ingredients.id"), nullable=False)

    quantity      = Column(Float, nullable=False)
    unit          = Column(String, nullable=False)

    recipe     = relationship("Recipe", back_populates="items")
    ingredient = relationship("Ingredient")

    __table_args__ = (
        UniqueConstraint("recipe_id", "ingredient_id", name="uq_recipe_ingredient"),
    )


class Menu(Base):
    __tablename__ = "menus"

    id    = Column(Integer, primary_key=True)
    name  = Column(String, unique=True, nullable=False)

    items = relationship(
        "MenuItem",
        back_populates="menu",
        cascade="all, delete-orphan",
        passive_deletes=False,
    )


class MenuItem(Base):
    __tablename__ = "menu_items"

    id        = Column(Integer, primary_key=True)
    menu_id   = Column(Integer, ForeignKey("menus.id"), nullable=False)
    recipe_id = Column(Integer, ForeignKey("recipes.id"), nullable=False)
    batches   = Column(Float, default=1.0)

    menu   = relationship("Menu", back_populates="items")
    recipe = relationship("Recipe")


class StockMovement(Base):
    __tablename__ = "stock_movements"

    id            = Column(Integer, primary_key=True)
    ingredient_id = Column(Integer, ForeignKey("ingredients.id"), nullable=False)
    # quantité en unité de base (+ entrée / - sortie)
    quantity_base = Column(Float, nullable=False)
    movement_type = Column(String, nullable=False)  # 'in' | 'out' | 'adjust'
    unit_cost     = Column(Float, default=0.0)
    note          = Column(String, default="")
    created_at    = Column(DateTime, default=datetime.datetime.utcnow)
class Menu(Base):
    __tablename__ = "menus"
    id = Column(Integer, primary_key=True)
    name = Column(String, unique=True, nullable=False)
    notes = Column(String, default="")
    recipes = relationship("MenuRecipe", back_populates="menu", cascade="all, delete-orphan")


class MenuRecipe(Base):
    __tablename__ = "menu_recipes"
    id = Column(Integer, primary_key=True)
    menu_id = Column(Integer, ForeignKey("menus.id"), nullable=False)
    recipe_id = Column(Integer, ForeignKey("recipes.id"), nullable=False)

    menu = relationship("Menu", back_populates="recipes")
    recipe = relationship("Recipe")

    __table_args__ = (UniqueConstraint("menu_id", "recipe_id", name="uix_menu_recipe"),)

# -------------------------------------------------------------------
#  INIT DB (création et patch doux pour 'instructions' en SQLite)
# -------------------------------------------------------------------
def init_db():
    """Crée les tables. Ajoute la colonne 'instructions' à recipes si absente (SQLite)."""
    Base.metadata.create_all(bind=engine)

    # Patch doux (SQLite) pour s'assurer que 'instructions' existe dans 'recipes'
    # Sans effet si déjà présent ou si on est sur Postgres.
    try:
        with engine.connect() as conn:
            res = conn.exec_driver_sql("PRAGMA table_info(recipes)")
            cols = [str(r[1]).lower() for r in res]
            if "instructions" not in cols:
                conn.exec_driver_sql("ALTER TABLE recipes ADD COLUMN instructions TEXT DEFAULT ''")
    except Exception:
        pass
