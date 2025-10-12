import streamlit as st
import pandas as pd
from sqlalchemy.orm import Session
from sqlalchemy import select

from db import Recipe, Ingredient, RecipeItem
from units import normalize_unit, to_base_units

# Optionnel : export auto vers Google Sheets si activé dans secrets
try:
    from sheets_sync import auto_export  # ne casse pas si non configuré
except Exception:  # pragma: no cover
    def auto_export(*args, **kwargs):
        pass


def _recalc_cost(db: Session, recipe: Recipe) -> float:
    """Calcule le coût total de la recette (pour 'servings' portions)."""
    total = 0.0
    items = db.execute(
        select(RecipeItem).where(RecipeItem.recipe_id == recipe.id)
    ).scalars().all()

    for it in items:
        ing = it.ingredient
        if not ing:
            continue
        qty = float(it.quantity or 0.0)
        unit = normalize_unit(it.unit or ing.base_unit or "g")
        if qty <= 0:
            continue
        try:
            base_qty = to_base_units(qty, unit, ing.base_unit or "g")
        except Exception:
            # unité non convertible : on ignore
            continue
        total += (base_qty * float(ing.price_per_base_unit or 0.0))
    return total


def recipes_page(db: Session) -> None:
    st.header("Recettes")

    # ------------------------------------------------------------------
    # 1) Création / sélection de recette
    # ------------------------------------------------------------------
    st.subheader("Créer ou choisir une recette")

    col1, col2, col3 = st.columns([3, 2, 1])
    with col1:
        name = st.text_input("Nom de la recette *", placeholder="Ex. Gnocchis à la ricotta")
    with col2:
        category = st.text_input("Catégorie", placeholder="Entrée, Plat, Dessert…")
    with col3:
        servings = st.number_input("Portions (servings)", min_value=1, value=1, step=1)

    c1, c2 = st.columns([1, 1])
    with c1:
        if st.button("💾 Enregistrer / Mettre à jour"):
            if not name.strip():
                st.warning("Le nom de la recette est requis.")
            else:
                rec = db.query(Recipe).filter(Recipe.name.ilike(name.strip())).first()
                if not rec:
                    rec = Recipe(name=name.strip())
                    db.add(rec)
                    db.commit()
                    db.refresh(rec)
                # MAJ des champs
                rec.category = (category or "").strip()
                rec.servings = int(servings)
                db.commit()
                auto_export(db, "recipes")
                st.success(f"Recette « {rec.name} » enregistrée.")
                st.session_state["current_recipe_id"] = rec.id
    with c2:
        # sélecteur d'une recette existante
        existing = db.execute(select(Recipe).order_by(Recipe.name)).scalars().all()
        sel = st.selectbox(
            "Ou sélectionner une recette existante",
            ["(aucune)"] + [r.name for r in existing],
            index=0,
        )
        if sel != "(aucune)":
            r = next((x for x in existing if x.name == sel), None)
            if r:
                st.session_state["current_recipe_id"] = r.id

    # Récup recette courante
    recipe = None
    if "current_recipe_id" in st.session_state:
        recipe = db.query(Recipe).get(st.session_state["current_recipe_id"])

    if not recipe:
        st.info("Crée une recette ou sélectionne-en une pour continuer.")
        return

    st.markdown(f"### ✏️ Édition — **{recipe.name}** (servings: {recipe.servings})")

    # ------------------------------------------------------------------
    # 2) Ingrédients de la recette (AVANT les étapes)
    # ------------------------------------------------------------------
    st.subheader("Ingrédients de la recette")

    with st.popover("➕ Ajouter un ingrédient", use_container_width=True):
        ings = db.execute(select(Ingredient).order_by(Ingredient.name)).scalars().all()
        if not ings:
            st.warning("Aucun ingrédient dans le catalogue. Ajoute d’abord des ingrédients.")
        else:
            ing_map = {f"{i.name} — ({i.category})": i for i in ings}
            choice = st.selectbox("Ingrédient", list(ing_map.keys()))
            qty = st.number_input("Quantité", min_value=0.0, value=100.0, step=10.0)
            unit = st.selectbox("Unité", ["mg", "g", "kg", "ml", "l", "unit"], index=1)

            if st.button("Ajouter / Mettre à jour"):
                i = ing_map[choice]
                existing_item = db.execute(
                    select(RecipeItem).where(
                        RecipeItem.recipe_id == recipe.id,
                        RecipeItem.ingredient_id == i.id,
                    )
                ).scalars().first()
                if existing_item:
                    existing_item.quantity = float(qty)
                    existing_item.unit = normalize_unit(unit)
                else:
                    db.add(
                        RecipeItem(
                            recipe_id=recipe.id,
                            ingredient_id=i.id,
                            quantity=float(qty),
                            unit=normalize_unit(unit),
                        )
                    )
                db.commit()
                auto_export(db, "recipe_items")
                st.success("Ingrédient ajouté / mis à jour.")
                st.rerun()

    # Tableau des items
    items = db.execute(
        select(RecipeItem).where(RecipeItem.recipe_id == recipe.id)
    ).scalars().all()

    if items:
        rows = []
        for it in items:
            rows.append(
                {
                    "Ingrédient": it.ingredient.name if it.ingredient else "—",
                    "Catégorie": it.ingredient.category if it.ingredient else "",
                    "Quantité": it.quantity,
                    "Unité": it.unit,
                    "Base": it.ingredient.base_unit if it.ingredient else "",
                    "Prix base ($/unité)": round(float(it.ingredient.price_per_base_unit or 0.0), 6)
                    if it.ingredient
                    else 0.0,
                }
            )
        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
    else:
        st.info("Pas encore d’ingrédients dans cette recette.")

    # Retrait d’un ingrédient
    with st.popover("🗑️ Retirer un ingrédient", use_container_width=True):
        if items:
            sel_ing = st.selectbox(
                "Choisir un ingrédient à retirer",
                [it.ingredient.name for it in items if it.ingredient],
            )
            if st.button("Retirer"):
                tgt = next((it for it in items if it.ingredient and it.ingredient.name == sel_ing), None)
                if tgt:
                    db.delete(tgt)
                    db.commit()
                    auto_export(db, "recipe_items")
                    st.success("Ingrédient retiré.")
                    st.rerun()
        else:
            st.caption("Aucun ingrédient à retirer.")

    # ------------------------------------------------------------------
    # 3) Étapes de préparation (instructions)
    # ------------------------------------------------------------------
    st.subheader("Étapes de préparation")

    instructions = st.text_area(
        "Instructions",
        value=recipe.instructions or "",
        height=200,
        placeholder="Décris clairement les étapes de préparation…",
    )
    if st.button("💾 Enregistrer les instructions"):
        recipe.instructions = instructions
        db.commit()
        auto_export(db, "recipes")
        st.success("Instructions enregistrées.")

    # ------------------------------------------------------------------
    # 4) Coût estimé
    # ------------------------------------------------------------------
    st.subheader("Coût estimé")
    try:
        total_cost = _recalc_cost(db, recipe)
        st.metric(
            label=f"Coût total pour {recipe.servings} portion(s)",
            value=f"{total_cost:,.2f} $".replace(",", " ").replace(".", ","),
        )
        if recipe.servings and recipe.servings > 0:
            per_serv = total_cost / float(recipe.servings)
            st.caption(f"≈ {per_serv:,.2f} $ / portion".replace(",", " ").replace(".", ","))
    except Exception as e:
        st.warning(f"Impossible de calculer le coût (vérifie unités/prix). Détail: {e}")
