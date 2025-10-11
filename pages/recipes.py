import streamlit as st
import pandas as pd
from sqlalchemy.orm import Session
from db import Recipe, Ingredient, RecipeItem
from pages.logic import recipe_cost
from units import normalize_unit

def _rerun():
    if hasattr(st, "rerun"):
        st.rerun()
    elif hasattr(st, "experimental_rerun"):
        st.experimental_rerun()

def recipes_page(db: Session) -> None:
    st.header("Recettes")

    # ------------------------------------------------------------------
    # Créer / modifier une recette (inclut champ 'instructions')
    # ------------------------------------------------------------------
    with st.expander("Créer ou modifier une recette", expanded=True):
        colA, colB = st.columns([2, 1])
        name = colA.text_input("Nom de la recette *")
        servings = colB.number_input("Nombre de portions", min_value=1, value=1)
        category = st.text_input("Catégorie", value="Général")

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
                        instructions=(instructions or "").strip(),
                    )
                    db.add(r)
                else:
                    r.servings = int(servings)
                    r.category = category.strip() or "Général"
                    r.instructions = (instructions or "").strip()
                db.commit()
                st.success(f"Recette enregistrée : {r.name}")

    st.divider()

    # ------------------------------------------------------------------
    # Sélection d'une recette existante
    # ------------------------------------------------------------------
    recipes = db.query(Recipe).order_by(Recipe.name).all()
    if not recipes:
        st.info("Créez d’abord une recette ci-dessus.")
        return

    sel_name = st.selectbox("Sélectionner une recette", [r.name for r in recipes])
    recipe: Recipe = db.query(Recipe).filter(Recipe.name == sel_name).first()

    # ------------------------------------------------------------------
    # Édition des ingrédients de la recette (menus déroulants depuis BD)
    # ------------------------------------------------------------------
    st.subheader(f"Ingrédients — {recipe.name}")

    all_ings = db.query(Ingredient).order_by(Ingredient.name).all()
    if not all_ings:
        st.warning("Aucun ingrédient dans le catalogue. Ajoutez-en d’abord dans l’onglet Ingrédients.")
    else:
        # Filtre par catégorie
        cats = sorted({(i.category or "Autre") for i in all_ings})
        c1, c2, c3 = st.columns([1, 2, 2])
        cat_filter = c1.selectbox("Catégorie", ["(toutes)"] + cats)
        if cat_filter != "(toutes)":
            filtered_ings = [i for i in all_ings if (i.category or "Autre") == cat_filter]
        else:
            filtered_ings = all_ings

        # Select d’ingrédient
        ing_labels = [f"{i.name} — ({i.category or 'Autre'})" for i in filtered_ings]
        sel_label = c2.selectbox("Ingrédient", ing_labels) if filtered_ings else None
        sel_ing = filtered_ings[ing_labels.index(sel_label)] if sel_label else None

        # Unités compatibles selon l'unité de base de l'ingrédient choisi
        def unit_choices_for_base(base: str):
            if base == "g":
                return ["mg", "g", "kg"]
            if base == "ml":
                return ["ml", "l"]
            return ["unit"]

        qty = c3.number_input("Quantité", min_value=0.0, value=100.0, step=10.0)
        unit = st.selectbox(
            "Unité",
            unit_choices_for_base(sel_ing.base_unit if sel_ing else "g"),
            index=1 if (sel_ing and sel_ing.base_unit in ("g", "ml")) else 0
        )

        if st.button("Ajouter / Mettre à jour l’ingrédient"):
            if not sel_ing:
                st.error("Sélectionne un ingrédient.")
            else:
                existing = db.query(RecipeItem).filter(
                    RecipeItem.recipe_id == recipe.id,
                    RecipeItem.ingredient_id == sel_ing.id
                ).first()
                if existing:
                    existing.quantity = float(qty)
                    existing.unit = normalize_unit(unit)
                else:
                    db.add(RecipeItem(
                        recipe_id=recipe.id,
                        ingredient_id=sel_ing.id,
                        quantity=float(qty),
                        unit=normalize_unit(unit),
                    ))
                db.commit()
                st.success("Ingrédient ajouté / mis à jour.")
                st.rerun()

    # Tableau des ingrédients de la recette
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
    if not df.empty:
        st.dataframe(
            df.style.format({
                "Quantité": "{:.2f}",
                "Prix base ($/unité)": "{:.4f}",
            }),
            use_container_width=True
        )
    else:
        st.info("Aucun ingrédient ajouté pour cette recette.")

    # Retirer un ingrédient
    with st.popover("Retirer un ingrédient"):
        if items:
            sel = st.selectbox("Choisir un ingrédient", [it.ingredient.name for it in items])
            if st.button("Retirer"):
                tgt = next((it for it in items if it.ingredient.name == sel), None)
                if tgt:
                    db.delete(tgt)
                    db.commit()
                    st.success("Ingrédient retiré.")
                    st.rerun()

    # ------------------------------------------------------------------
    # Étapes de préparation (édition + aperçu numéroté)
    # ------------------------------------------------------------------
    st.subheader("Étapes de préparation")
    edited = st.text_area(
        "Modifier les étapes",
        value=(recipe.instructions or ""),
        height=220,
        placeholder="Ex.: 1) Mélanger la farine et le lait...\n2) Ajouter les œufs...\n3) Cuire 2 min de chaque côté...",
    )
    if st.button("Enregistrer les étapes"):
        recipe.instructions = (edited or "").strip()
        db.commit()
        st.success("Étapes enregistrées.")

    st.caption("Aperçu (numéroté)")
    preview = [ln.strip() for ln in (edited or "").splitlines() if ln.strip()]
    if preview:
        st.markdown("\n".join([f"{i+1}. {line}" for i, line in enumerate(preview)]))
    else:
        st.write("_Aucune étape pour le moment._")

    # ------------------------------------------------------------------
    # Coûts
    # ------------------------------------------------------------------
    st.subheader("Coûts")
    cost = recipe_cost(db, recipe.id)
    c1, c2 = st.columns(2)
    c1.metric("Coût total de la recette ($)", f"{cost['total_cost']:.2f}")
    c2.metric("Coût par portion ($)", f"{cost['per_serving']:.2f}")
