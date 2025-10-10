from __future__ import annotations
from typing import Dict
from sqlalchemy.orm import Session
from db import Ingredient, Recipe, RecipeItem, Menu
from units import to_base_units, normalize_unit

def compute_price_per_base_unit(pack_size: float, pack_unit: str, base_unit: str, purchase_price: float) -> float:
    pack_unit = normalize_unit(pack_unit)
    pack_in_base = to_base_units(pack_size, pack_unit, base_unit)
    if pack_in_base <= 0: raise ValueError("Pack size must be > 0")
    return purchase_price / pack_in_base

def recipe_cost(db: Session, recipe_id: int) -> dict:
    r = db.get(Recipe, recipe_id)
    if not r: return {"total_cost": 0.0, "per_serving": 0.0}
    total = 0.0
    for it in r.items:
        ing: Ingredient = it.ingredient
        qty_base = to_base_units(it.quantity, normalize_unit(it.unit), ing.base_unit)
        total += qty_base * ing.price_per_base_unit
    return {"total_cost": total, "per_serving": total / max(1, r.servings)}

def menu_aggregate_needs(db: Session, menu_id: int) -> Dict[int, dict]:
    m = db.get(Menu, menu_id)
    if not m: return {}
    needs: Dict[int, dict] = {}
    for mi in m.items:
        r = mi.recipe; factor = float(mi.batches or 1.0)
        for it in r.items:
            ing = it.ingredient
            qty_base = to_base_units(it.quantity, normalize_unit(it.unit), ing.base_unit) * factor
            rec = needs.get(ing.id) or {"name": ing.name, "base_unit": ing.base_unit, "total_qty_base": 0.0, "supplier": (ing.supplier.name if ing.supplier else "")}
            rec["total_qty_base"] += qty_base
            needs[ing.id] = rec
    return needs
