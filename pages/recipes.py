import streamlit as st
import pandas as pd
from sqlalchemy.orm import Session
from db import Ingredient, Recipe, RecipeItem
from pages.logic import recipe_cost
from units import normalize_unit

def recipes_page(db: Session):
    st.header("Recettes")
    with st.expander("➕ Créer / Modifier une recette", expanded=True):
        left, right = st.columns([2,1])
        with left:
            name = st.text_input("Nom de la recette *")
            category = st.text_input("Catégorie", value="Général")
            servings = st.number_input("Portions", min_value=1, value=4, step=1)
        with right:
            if st.button("Enregistrer la recette"):
                if not name.strip():
                    st.error("Le nom est requis.")
                else:
                    existing = db.query(Recipe).filter(Recipe.name.ilike(name.strip())).first()
                    if existing:
                        existing.category = category.strip() or "Général"
                        existing.servings = int(servings)
                        db.commit(); st.success(f"Recette mise à jour: {existing.name}")
                    else:
                        r = Recipe(name=name.strip(), category=category.strip() or "Général", servings=int(servings))
                        db.add(r); db.commit(); st.success(f"Recette créée: {r.name}")

    st.divider()
    recipes = db.query(Recipe).order_by(Recipe.name).all()
    if not recipes:
        st.info("Créez d'abord une recette ci-dessus."); return
    sel_name = st.selectbox("Sélectionner une recette", [r.name for r in recipes])
    recipe = db.query(Recipe).filter(Recipe.name == sel_name).first()

    st.subheader(f"Ingrédients de: {recipe.name}")
    with st.popover("➕ Ajouter un ingrédient à la recette"):
        ings = db.query(Ingredient).order_by(Ingredient.name).all()
        ing_map = {f"{i.name} — ({i.category})": i for i in ings}
        choice = st.selectbox("Ingrédient", list(ing_map.keys()) if ing_map else ["(aucun)"])
        qty = st.number_input("Quantité", min_value=0.0, value=100.0, step=10.0)
        unit = st.selectbox("Unité", ["mg","g","kg","ml","l","unit"], index=1)
        if st.button("Ajouter à la recette"):
            if ings and choice in ing_map:
                i = ing_map[choice]
                existing = db.query(RecipeItem).filter(RecipeItem.recipe_id==recipe.id, RecipeItem.ingredient_id==i.id).first()
                if existing:
                    existing.quantity = float(qty); existing.unit = normalize_unit(unit)
                else:
                    db.add(RecipeItem(recipe_id=recipe.id, ingredient_id=i.id, quantity=float(qty), unit=normalize_unit(unit)))
                db.commit(); st.success("Ingrédient ajouté/mis à jour."); st.experimental_rerun()

    items = db.query(RecipeItem).filter(RecipeItem.recipe_id == recipe.id).all()
    rows = []
    for it in items:
        rows.append({
            "Ingrédient": it.ingredient.name,
            "Quantité": it.quantity,
            "Unité": it.unit,
            "Prix base ($/base)": round(it.ingredient.price_per_base_unit, 6),
            "Fournisseur": (it.ingredient.supplier.name if it.ingredient.supplier else ""),
        })
    st.dataframe(pd.DataFrame(rows), use_container_width=True)

    cost = recipe_cost(db, recipe.id)
    c1, c2 = st.columns(2)
    c1.metric("Coût total de la recette ($)", f"{cost['total_cost']:.2f}")
    c2.metric("Coût par portion ($)", f"{cost['per_serving']:.2f}")

    with st.popover("🗑️ Retirer un ingrédient de la recette"):
        if items:
            sel = st.selectbox("Sélectionner", [it.ingredient.name for it in items])
            if st.button("Retirer"):
                target = next((it for it in items if it.ingredient.name == sel), None)
                if target:
                    db.delete(target); db.commit(); st.success("Ingrédient retiré."); st.experimental_rerun()
