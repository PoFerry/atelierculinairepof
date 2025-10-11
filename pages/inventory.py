import streamlit as st
import pandas as pd
from sqlalchemy.orm import Session
from db import Ingredient, StockMovement
from logic import current_stock_map, add_stock_movement
from units import normalize_unit

def inventory_page(db: Session):
    st.header("Inventaire")

    # --- Vue du stock actuel ---
    st.subheader("Stock actuel (par ingrédient)")
    stock = current_stock_map(db)
    ings = db.query(Ingredient).order_by(Ingredient.name).all()
    rows = [{
        "Ingrédient": i.name,
        "Catégorie": i.category,
        "Unité de base": i.base_unit,
        "Stock (base)": round(stock.get(i.id, 0.0), 3)
    } for i in ings]
    st.dataframe(pd.DataFrame(rows), use_container_width=True)

    # --- Ajouter un mouvement ---
    st.divider()
    st.subheader("Mouvements de stock")
    with st.expander("➕ Ajouter un mouvement", expanded=True):
        left, right = st.columns([2, 1])
        with left:
            ing_map = {f"{i.name} — ({i.base_unit})": i for i in ings}
            choice = st.selectbox("Ingrédient", list(ing_map.keys()) if ing_map else ["(aucun)"])
            movement_type = st.selectbox("Type", ["in", "out", "adjust"], help="'in' entrée, 'out' sortie, 'adjust' ajustement +/-")
            qty = st.number_input("Quantité", min_value=0.0, value=100.0, step=10.0)
            unit = st.selectbox("Unité de la quantité", ["mg", "g", "kg", "ml", "l", "unit"], index=1)
            unit_cost = st.number_input("Coût unitaire (optionnel, $/unité de base)", min_value=0.0, value=0.0, step=0.01)
            note = st.text_input("Note (optionnel)")
        with right:
            if st.button("Ajouter"):
                if ing_map and choice in ing_map:
                    ing = ing_map[choice]
                    try:
                        add_stock_movement(db, ing, qty, normalize_unit(unit), movement_type, unit_cost=unit_cost, note=note)
                        st.success("Mouvement ajouté.")
                        st.experimental_rerun()
                    except Exception as e:
                        st.error(f"Erreur: {e}")

    # --- Historique des mouvements ---
    moves = db.query(StockMovement).order_by(StockMovement.created_at.desc()).limit(200).all()
    dfm = pd.DataFrame([{
        "Date": m.created_at.strftime("%Y-%m-%d %H:%M"),
        "Ingrédient": next((i.name for i in ings if i.id == m.ingredient_id), m.ingredient_id),
        "Quantité (base)": round(m.quantity_base, 3),
        "Type": m.movement_type,
        "Coût unitaire ($/base)": m.unit_cost,
        "Note": m.note
    } for m in moves])
    st.dataframe(dfm, use_container_width=True)
