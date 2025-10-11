import streamlit as st
import pandas as pd
from sqlalchemy.orm import Session
from db import Recipe, Ingredient, RecipeItem
from pages.logic import recipe_cost
from units import normalize_unit, to_base_units

def recipes_page(db: Session):
    st.header("Recettes")

    # --- Création / modification d’une recette ---
    with st.expander("➕ Créer ou modifier une recette", expanded=True):
        colA, colB = st.columns([2, 1])
        name = colA.text_input("Nom de la recette")
        servings = colB.number_input("Nombre de portions", min_value=1, value=1)
        category = st.text_input("Catégorie")
        if st.button("Enregistrer la recette"):
            if not name.strip():
                st.warning("Nom requis.")
            else:
                r = db.query(Recipe).filter(Recipe.name.ilike(name.strip())).first()
                if not r:
                    r = Recipe(name=name.strip(), servings=servings, category=category)
                    db.add(r)
                else:
                    r.servings = servings
                    r.category = category
                db.commit()
                st.success(f"Recette enregistrée : {r.name}")

    # --- Liste des recettes ---
    recipes = db.query(Recipe).order_by(Recipe.name).all()
    st.subheader("📜 Liste des recettes")
    st.dataframe(pd.DataFrame([{
        "Nom": r.name,
        "Catégorie": r.category,
        "Portions": r.servings
    } for r in recipes]), use_container_width=True)

    # --- Détail d’une recette ---
    st.divider()
    sel = st.selectbox("Voir / modifier la recette :", [r.name for r in recipes] if recipes else [])
    if sel:
        r = db.query(Recipe).filter(Recipe.name == sel).first()
        st.write(f"### {r.name} — {r.category}")
        items = db.query(RecipeItem).filter(RecipeItem.recipe_id == r.id).all()
        df = pd.DataFrame([{
            "Ingrédient": db.get(Ingredient, it.ingredient_id).name,
            "Quantité": it.quantity,
            "Unité": it.unit
        } for it in items])
        st.dataframe(df, use_container_width=True)

        cost = recipe_cost(db, r.id)
        st.info(f"💲 Coût total : {cost['total_cost']:.2f}  |  Par portion : {cost['per_serving']:.2f}")
