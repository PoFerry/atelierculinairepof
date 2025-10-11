import streamlit as st
import pandas as pd
from sqlalchemy.orm import Session
from db import Recipe, Ingredient, RecipeItem
from pages.logic import recipe_cost
from units import normalize_unit


def recipes_page(db: Session) -> None:
    st.header("Recettes")

    # ----- Creer / modifier une recette -----
    with st.expander("Creer ou modifier une recette", expanded=True):
        colA, colB = st.columns([2, 1])
        name = colA.text_input("Nom de la recette *")
        servings = colB.number_input("Nombre de portions", min_value=1, value=1)
        category = st.text_input("Categorie", value="General")

        # Etapes de preparation (texte libre)
        instructions = st.text_area(
            "Etapes de preparation",
            placeholder="Decrivez ici les etapes (ex. 1) Melanger... 2) Cuire... 3) Dresser...)",
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
                        category=category.strip() or "General",
                        instructions=instructions.strip(),
                    )
                    db.add(r)
                else:
                    r.servings = int(servings)
                    r.category = category.strip() or "General"
                    r.instructions = instructions.strip()
                db.commit()
                st.success(f"Recette enregistree : {r.name}")

    st.divider()

    # ----- Selection d'une recette existante -----
    recipes = db.query(Recipe).order_by(Recipe.name).all()
    if not recipes:
        st.info("Creez d'abord une recette ci-dessus.")
        return

    sel_name = st.selectbox("Selectionner une recette", [r.name for r in recipes])
    recipe: Recipe = db.query(Recipe).filter(Recipe.name == sel_name).first()

    # ----- Edition des ingredients de la recette -----
    st.subheader(f"Ingredients — {recipe.name}")

    with st.popover("Ajouter un ingredient a la recette", use_container_width=True):
        ings = db.query(Ingredient).order_by(Ingredient.name).all()
        if not ings:
            st.warning("Aucun ingredient dans le catalogue. Ajoutez-en d'abord dans l'onglet Ingredients.")
        else:
            ing_map = {f"{i.name} — ({i.category})": i for i in ings}
            choice = st.selectbox("Ingredient", list(ing_map.keys()))
            qty = st.number_input("Quantite", min_value=0.0, value=100.0, step=10.0)
            unit = st.selectbox("Unite", ["mg", "g", "kg", "ml", "l", "unit"], index=1)

            if st.button("Ajouter / Mettre a jour"):
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
                st.success("Ingredient ajoute / mis a jour.")
                st.experimental_rerun()

    items = db.query(RecipeItem).filter(RecipeItem.recipe_id == recipe.id).all()
    rows = []
    for it in items:
        rows.append({
            "Ingredient": it.ingredient.name,
            "Quantite": it.quantity,
            "Unite": it.unit,
            "Fournisseur": (it.ingredient.supplier.name if it.ingredient.supplier else ""),
            "Prix base ($/unite)": round(it.ingredient.price_per_base_unit, 6),
        })
    df = pd.DataFrame(rows)
    if not df.empty:
        st.dataframe(
            df.style.format({
                "Quantite": "{:.2f}",
                "Prix base ($/unite)": "{:.4f}",
            }),
            use_container_width=True
        )
    else:
        st.info("Aucun ingredient ajoute pour cette recette.")

    # ----- Retirer un ingredient -----
    with st.popover("Retirer un ingredient"):
        if items:
            sel = st.selectbox("Choisir un ingredient", [it.ingredient.name for it in items])
            if st.button("Retirer"):
                tgt = next((it for it in items if it.ingredient.name == sel), None)
                if tgt:
                    db.delete(tgt)
                    db.commit()
                    st.success("Ingredient retire.")
                    st.experimental_rerun()

    # ----- Etapes de preparation -----
    st.subheader("Etapes de preparation")
    edited = st.text_area(
        "Modifier les etapes",
        value=(recipe.instructions or ""),
        height=220,
        placeholder="Ex.: 1) Melanger la farine et le lait...\n2) Ajouter les oeufs...\n3) Cuire 2 min de chaque cote...",
    )
    if st.button("Enregistrer les etapes"):
        recipe.instructions = (edited or "").strip()
        db.commit()
        st.success("Etapes enregistrees.")

    # Apercu numerote des etapes
    st.caption("Apercu (numerote)")
    preview = [ln.strip() for ln in (edited or "").splitlines() if ln.strip()]
    if preview:
        st.markdown("\n".join([f"{i+1}. {line}" for i, line in enumerate(preview)]))
    else:
        st.write("_Aucune etape pour le moment._")

    # ----- Couts -----
    st.subheader("Couts")
    cost = recipe_cost(db, recipe.id)
    c1, c2 = st.columns(2)
    c1.metric("Cout total de la recette ($)", f"{cost['total_cost']:.2f}")
    c2.metric("Cout par portion ($)", f"{cost['per_serving']:.2f}")
