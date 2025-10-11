import streamlit as st
import pandas as pd
from sqlalchemy.orm import Session
from db import Recipe, Ingredient, RecipeItem
from pages.logic import recipe_cost
from units import normalize_unit

def recipes_page(db: Session):
    st.header("Recettes")

    # -----------------------------
    # Créer / mettre à jour la fiche recette
    # -----------------------------
    with st.expander("➕ Créer ou modifier une recette", expanded=True):
        colA, colB = st.columns([2, 1])
        name = colA.text_input("Nom de la recette *")
        servings = colB.number_input("Nombre de portions", min_value=1, value=1)
        category = st.text_input("Catégorie", value="Général")

        # Étapes de préparation (texte libre)
        instructions = st.text_area(
            "Étapes de préparation",
            placeholder="Décrivez ici les étapes (ex. 1) Mélanger… 2) Cuire… 3) Dresser…)",
            height=160,
        )

        if st.button("Enregistrer la recette"):
            if not name.strip():
                st.warning("Nom requis.")
            else:
                r = db.query(Recipe).filter(Recipe.name.ilike(name.strip())).first()
                if not r:
                    r = Recipe(
                        name=name.strip(),
                        servings=int(servings),
                        category=category.strip() or "Général",
                        instructions=instructions.strip(),
                    )
                    db.add(r)
                else:
                    r.servings = int(servings)
                    r.category = category.strip() or "Général"
                    r.instructions = instructions.strip()
                db.commit()
                st.success(f"Recette enregistrée : {r.name}")

    st.divider()

    # -----------------------------
    # Sélection d'une recette existante
    # -----------------------------
    recipes = db.query(Recipe).order_by(Recipe.name).all()
    if not recipes:
        st.info("Créez d’abord une recette ci-dessus.")
        return

    sel_name = st.selectbox("Sélectionner une recette", [r.name for r in recipes])
    recipe: Recipe = db.query(Recipe).filter(Recipe.name == sel_name).first()

    # -----------------------------
    # Édition des ingrédients de la recette
    # -----------------------------
    st.subheader(f"Ingrédients — {recipe.name}")

    with st.popover("➕ Ajouter un ingrédient à la recette", use_container_width=True):
        ings = db.query(Ingredient).order_by(Ingredient.name).all()
        if not ings:
            st.warning("Aucun ingrédient dans le catalogue. Ajoutez-en d’abord dans l’onglet Ingrédients.")
        else:
            ing_map = {f"{i.name} — ({i.category})": i for i in ings}
            choice = st.selectbox("Ingrédient", list(ing_map.keys()))
            qty = st.number_input("Quantité", min_value=0.0, value=100.0, step=10.0)
            unit = st.selectbox("Unité", ["mg", "g", "kg", "ml", "l", "unit"], index=1)

            if st.button("Ajouter / Mettre à jour"):
                i = ing_map[choice]
                existing = db.query(RecipeItem).filter(
                    RecipeItem.recipe_id == recipe.id,
                    RecipeItem.ingredient_id == i.id
                ).first()
                if existing:
                    existing.quantity = float(qty)
                    existing.unit = normalize_unit(unit)
                else:
                    db.add(RecipeItem(
                        recipe_id=recipe.id,
                        ingredient_id=i.id,
                        quantity=float(qty),
                        unit=normalize_unit(unit),
                    ))
                db.commit()
                st.success("Ingrédient ajouté / mis à jour.")
                st.experimental_rerun()

    items = db.query(RecipeItem).filter(RecipeItem.recipe_id == recipe.id).all()
    rows = []
    for it in items:
        rows.append({
            "Ingrédient": it.ingredient.name,
            "Quantité": it.quantity,
            "Unité": it.unit,
            "Fournisseur": (it.ingredient.supplier.name if it.ingredient.supplier else ""),
            "Prix base ($/unité)": round(it.ingredient.price_per_base_unit, 6),
        })
    df = pd.DataFrame(rows)
    st.dataframe(df, use_container_width=True)

    # Retirer un ingrédient
    with st.popover("🗑️ Retirer un ingrédient"):
        if items:
            sel = st.selectbox("Choisir un ingrédient", [it.ingredient.name for it in items])
            if st.button("Retirer"):
                tgt = next((it for it in items if it.ingredient.name == sel), None)
                if tgt:
                    db.delete(tgt)
                    db.commit()
                    st.success("Ingrédient retiré.")
                    st.experimental_rerun()

    # -----------------------------
    # Étapes de préparation (édition rapide)
    # -----------------------------
    st.subheader("👨‍🍳 Étapes de préparation")
    edited = st.text_area(
        "Modifier les étapes",
        value=(recipe.instructions or ""),
        height=220,
        placeholder="Ex.: 1) Mélanger la farine et le lait...\n2) Ajouter les œufs...\n3) Cuire 2 min de chaque côté...",
    )
    cols_steps = st.columns(2)
    if cols_steps[0].button("💾 Enregistrer les étapes"):
        recipe.instructions = (edited or "").strip()
        db.commit()
        st.success("Étapes enregistrées.")

    # -----------------------------
    # Coûts
    # -----------------------------
    st.subheader("💰 Coûts")
    cost = recipe_cost(db, recipe.id)
    c1, c2 = st.columns(2)
    c1.metric("Coût total de la recette ($)", f"{cost['total_cost']:.2f}")
    c2.metric("Coût par portion ($)", f"{cost['per_serving']:.2f}")
