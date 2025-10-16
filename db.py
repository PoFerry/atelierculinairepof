# db.py
from sqlalchemy import (
    create_engine,
    Column,
    Integer,
    String,
    Float,
    ForeignKey,
    UniqueConstraint,
    DateTime,
    inspect,
    text,
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
    supplier_code = Column(String, default="")

    pack_size = Column(Float, default=0.0)
    pack_unit = Column(String, default="g")
    purchase_price = Column(Float, default=0.0)
    price_per_base_unit = Column(Float, default=0.0)
    base_unit = Column(String, default="g")

    created_at = Column(DateTime, default=datetime.datetime.utcnow)

    __table_args__ = (
        UniqueConstraint("supplier_id", "supplier_code", name="uix_supplier_code"),
    )


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

@@ -112,25 +125,52 @@ class Menu(Base):
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

    insp = inspect(engine)
    try:
        ingredient_cols = {col["name"] for col in insp.get_columns("ingredients")}
    except Exception:
        ingredient_cols = set()

    if "supplier_code" not in ingredient_cols:
        with engine.begin() as conn:
            conn.execute(text("ALTER TABLE ingredients ADD COLUMN supplier_code TEXT DEFAULT ''"))

    try:
        ingredient_indexes = {idx["name"] for idx in insp.get_indexes("ingredients")}
    except Exception:
        ingredient_indexes = set()
    try:
        ingredient_uniques = {uc["name"] for uc in insp.get_unique_constraints("ingredients")}
    except Exception:
        ingredient_uniques = set()

    if ingredient_indexes.isdisjoint({"uix_supplier_code", "uix_ingredients_supplier_code"}) and "uix_supplier_code" not in ingredient_uniques:
        with engine.begin() as conn:
            conn.execute(
                text(
                    "CREATE UNIQUE INDEX IF NOT EXISTS uix_ingredients_supplier_code ON ingredients (supplier_id, supplier_code)"
                )
            )
