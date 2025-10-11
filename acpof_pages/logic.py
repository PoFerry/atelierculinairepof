# pages/logic.py
from __future__ import annotations
from typing import Dict
from sqlalchemy.orm import Session
from sqlalchemy import func
from db import Ingredient, Recipe, RecipeItem, Menu, StockMovement
from units import to_base_units, normalize_unit

def compute_price_per_base_unit(pack_size: float, pack_unit: str, base_unit: str, purchase_price: float) -> float:
    pack_unit = normalize_unit(pack_unit)
    pack_in_base = to_base_units(pack_size, pack_unit, base_unit)
    if pack_in_base <= 0:
        raise ValueError("Pack size must be > 0")
    return purchase_price / pack_in_base

def recipe_cost(db: Session, recipe_id: int) -> dict:
    r = db.get(Recipe, recipe_id)
    if not r:
        return {"total_cost": 0.0, "per_serving": 0.0}
    total = 0.0
    for it in r.items:
        ing: Ingredient = it.ingredient
        qty_base = to_base_units(it.quantity, normalize_unit(it.unit), ing.base_unit)
        total += qty_base * ing.price_per_base_unit
    return {"total_cost": total, "per_serving": total / max(1, r.servings)}

def menu_aggregate_needs(db: Session, menu_id: int) -> Dict[int, dict]:
    m = db.get(Menu, menu_id)
    if not m:
        return {}
    needs: Dict[int, dict] = {}
    for mi in m.items:
        r = mi.recipe
        factor = float(mi.batches or 1.0)
        for it in r.items:
            ing = it.ingredient
            qty_base = to_base_units(it.quantity, normalize_unit(it.unit), ing.base_unit) * factor
            rec = needs.get(ing.id) or {
                "name": ing.name,
                "base_unit": ing.base_unit,
                "total_qty_base": 0.0,
                "supplier": (ing.supplier.name if ing.supplier else "")
            }
            rec["total_qty_base"] += qty_base
            needs[ing.id] = rec
    return needs

def current_stock_map(db: Session) -> Dict[int, float]:
    res = (
        db.query(StockMovement.ingredient_id, func.coalesce(func.sum(StockMovement.quantity_base), 0.0))
        .group_by(StockMovement.ingredient_id)
        .all()
    )
    return {ing_id: float(qty) for (ing_id, qty) in res}

def add_stock_movement(db: Session, ingredient: Ingredient, qty: float, unit: str,
                       movement_type: str, unit_cost: float = 0.0, note: str = ""):
    qty_base = to_base_units(qty, normalize_unit(unit), ingredient.base_unit)
    if movement_type not in ("in", "out", "adjust"):
        raise ValueError("movement_type must be in|out|adjust")
    signed = qty_base
    if movement_type == "out":
        signed = -abs(qty_base)
    elif movement_type == "in":
        signed = abs(qty_base)
    mv = StockMovement(
        ingredient_id=ingredient.id,
        quantity_base=signed,
        movement_type=movement_type,
        unit_cost=float(unit_cost or 0.0),
        note=note,
    )
    db.add(mv)
    db.commit()
    return mv
