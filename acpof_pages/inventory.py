import streamlit as st
import pandas as pd
from sqlalchemy.orm import Session
from sqlalchemy import select, desc

from db import Ingredient, StockMovement
from units import normalize_unit, to_base_units

# Optionnel : export auto vers Google Sheets si activé dans secrets
try:
    from sheets_sync import auto_export  # ne casse pas si non configuré
except Exception:  # pragma: no cover
    def auto_export(*args, **kwargs):
        pass


def _rerun():
    try:
        st.rerun()
    except AttributeError:
        st.experimental_rerun()


def _pretty_qty(base_unit: str, qty: float) -> tuple[float, str]:
    """Formate une quantité en unités lisibles (kg/l si grand)."""
    base_unit = normalize_unit(base_unit or "g")
    if base_unit == "g":
        if qty >= 1000:
            return qty / 1000.0, "kg"
        return qty, "g"
    if base_unit == "ml":
        if qty >= 1000:
            return qty / 1000.0, "l"
        return qty, "ml"
    return qty, "unit"


def _current_stock_map(db: Session) -> dict[int, float]:
    """
    Retourne un dict {ingredient_id: stock_en_unite_base}.
    stock = somme( mouvements convertis vers base_unit, signe + pour IN, - pour OUT ).
    """
    stock: dict[int, float] = {}

    # On récupère tous les mouvements (si volumineux, filtrer par date ou paginer)
    moves = db.execute(select(StockMovement)).scalars().all()
    if not moves:
        return stock

    # Précharger les ingrédients référencés pour connaître leur base_unit
    ing_ids = list({m.ingredient_id for m in moves if m.ingredient_id is not None})
    if not ing_ids:
        return stock

    ings = db.execute(select(Ingredient).where(Ingredient.id.in_(ing_ids))).scalars().all()
    ing_map = {i.id: i for i in ings}

    for m in moves:
        i = ing_map.get(m.ingredient_id)
        if not i:
            continue
        try:
            qty_user = float(m.qty or 0.0)
        except Exception:
            qty_user = 0.0
        if qty_user == 0:
            continue

        unit_user = normalize_unit(m.unit or i.base_unit or "g")
        base_unit = normalize_unit(i.base_unit or "g")

        try:
            qty_base = to_base_units(abs(qty_user), unit_user, base_unit)
        except Exception:
            # unité non convertible — on ignore ce mouvement
            continue

        sign = 1.0 if (m.movement_type or "").lower().startswith("in") else -1.0
        delta = sign * qty_base

        stock[i.id] = stock.get(i.id, 0.0) + delta

    return stock


def inventory_page(db: Session):
    st.header("Inventaire")

    # -----------------------------
    # 1) Ajout d'un mouvement stock
    # -----------------------------
    st.subheader("Ajouter un mouvement")

    ings = db.execute(select(Ingredient).order_by(Ingredient.name)).scalars().all()
    if not ings:
        st.info("Aucun ingrédient dans le catalogue. Ajoutez-en d’abord dans « Ingrédients ».")
        return

    ing_label_map = {f"{i.name} — ({i.category or '—'})": i for i in ings}
    col1, col2 = st.columns([3, 2])
    with col1:
        ing_label = st.selectbox("Ingrédient", list(ing_label_map.keys()))
    with col2:
        move_type = st.selectbox("Type de mouvement", ["IN (entrée)", "OUT (sortie)"], index=0)

    c1, c2, c3 = st.columns([2, 1, 3])
    with c1:
        qty = st.number_input("Quantité", min_value=0.0, value=0.0, step=10.0)
    with c2:
        # propose l'unité de base par défaut pour éviter les confusions
        def_unit = normalize_unit(ing_label_map[ing_label].base_unit or "g")
        unit = st.selectbox("Unité", ["mg", "g", "kg", "ml", "l", "unit"],
                            index=["mg","g","kg","ml","l","unit"].index(def_unit) if def_unit in ["mg","g","kg","ml","l","unit"] else 1)
    with c3:
        notes = st.text_input("Notes (optionnel)", placeholder="Ex. livraison du 12/10, casse, ajustement...")

    btn_cols = st.columns([1, 1, 5])
    with btn_cols[0]:
        if st.button("Enregistrer le mouvement", type="primary", use_container_width=True):
            i = ing_label_map[ing_label]
            mv = StockMovement(
                ingredient_id=i.id,
                qty=float(qty),
                unit=normalize_unit(unit),
                movement_type="IN" if move_type.startswith("IN") else "OUT",
                notes=notes or "",
            )
            db.add(mv)
            db.commit()
            auto_export(db, "stock_movements")
            st.success("Mouvement enregistré.")
            _rerun()

    # ------------------------------------------
    # 2) Stock courant (agrégé par ingrédient)
    # ------------------------------------------
    st.subheader("Stock courant (agrégé)")
    stocks = _current_stock_map(db)

    rows = []
    for i in ings:
        base_qty = float(stocks.get(i.id, 0.0))
        disp_qty, disp_unit = _pretty_qty(i.base_unit or "g", base_qty)
        rows.append({
            "Ingrédient": i.name,
            "Catégorie": i.category or "",
            "Stock (affiché)": round(disp_qty, 3),
            "Unité": disp_unit,
            "Unité de base": normalize_unit(i.base_unit or "g"),
        })

    df_stock = pd.DataFrame(rows).sort_values(by=["Catégorie", "Ingrédient"])
    st.dataframe(df_stock, use_container_width=True, hide_index=True)

    # ------------------------------------------
    # 3) Historique des mouvements (dernier 100)
    # ------------------------------------------
    st.subheader("Historique des mouvements")
    last_moves = db.execute(
        select(StockMovement).order_by(desc(StockMovement.created_at)).limit(100)
    ).scalars().all()

    if last_moves:
        hist_rows = []
        for m in last_moves:
            ing = next((x for x in ings if x.id == m.ingredient_id), None)
            hist_rows.append({
                "Date": getattr(m, "created_at", None),
                "Ingrédient": ing.name if ing else f"#{m.ingredient_id}",
                "Type": (m.movement_type or "").upper(),
                "Quantité": m.qty,
                "Unité": m.unit,
                "Notes": m.notes or "",
            })
        st.dataframe(pd.DataFrame(hist_rows), use_container_width=True, hide_index=True)
    else:
        st.caption("Aucun mouvement enregistré pour l’instant.")
