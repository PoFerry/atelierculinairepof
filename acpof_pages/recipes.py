import streamlit as st
import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session
from db import Recipe, Ingredient, RecipeItem
from acpof_pages.logic import recipe_cost
from units import normalize_unit
from export_utils import build_recipe_pdf


# -------- helpers --------
def _rerun():
    try:
        st.rerun()
    except AttributeError:
        st.experimental_rerun()


def _unit_choices(base_unit: str):
    if base_unit == "g":
        return ["mg", "g", "kg"]
    if base_unit == "ml":
        return ["ml", "l"]
    return ["unit"]


def _ingredients_catalog(db: Session):
    rows = db.execute(
        select(Ingredient.id, Ingredient.name, Ingredient.category, Ingredient.base_unit).order_by(Ingredient.name)
    ).all()
    labels = []
    label_to_id = {}
    id_to_base = {}
    for ing_id, ing_name, ing_cat, base in rows:
        label = f"{ing_name} ({ing_cat or 'Autre'})"
        labels.append(label)
        label_to_id[label] = ing_id
        id_to_base[ing_id] = base
    return labels, label_to_id, id_to_base


def _empty_grid_df(n: int = 3) -> pd.DataFrame:
    return pd.DataFrame([{"Ingredient": "", "Quantite": 0.0, "Unite": ""} for _ in range(n)])


def recipes_page(db: Session) -> None:
    st.header("Recettes")

    # Charger le catalogue des ingredients pour les menus deroulants
    labels, label_to_id, id_to_base = _ingredients_catalog(db)

    # ------------------------------------------------------------------
    # 1) CREER / MODIFIER une recette + INGREDIENTS avant étapes
    # ------------------------------------------------------------------
    with st.expander("Créer ou modifier une recette", expanded=True):
        colA, colB = st.columns([2, 1])
        name = colA.text_input("Nom de la recette *")
        servings = colB.number_input("Nombre de portions", min_value=1, value=1)
        category = st.text_input("Catégorie", value="Général")

        st.caption("Ingrédients de la recette (saisir plusieurs lignes si besoin)")

        grid_key = "new_recipe_grid"
        if grid_key not in st.session_state:
            st.session_state[grid_key] = _empty_grid_df(3)

        add_cols = st.columns([1, 1, 4])
        to_add = add_cols[0].number_input("Ajouter lignes", min_value=1, max_value=20, value=3, step=1)
        if add_cols[1].button("Ajouter"):
            st.session_state[grid_key] = pd.concat(
                [st.session_state[grid_key], _empty_grid_df(int(to_add))], ignore_index=True
            )

        df_edit = st.data_editor(
            st.session_state[grid_key],
            key="editor_new_recipe",
            num_rows="dynamic",
            hide_index=True,
            use_container_width=True,
            column_config={
                "Ingredient": st.column_config.SelectboxColumn(
                    "Ingrédient",
                    options=[""] + labels,
                    help="Choisir un ingrédient du catalogue",
                ),
                "Quantite": st.column_config.NumberColumn(
                    "Quantité", min_value=0.0, step=1.0, format="%.2f"
                ),
                "Unite": st.column_config.SelectboxColumn(
                    "Unité",
                    options=["", "mg", "g", "kg", "ml", "l", "unit"],
                    help="Unité compatible avec l’unité de base de l’ingrédient",
                ),
            },
        )

        # Étapes de préparation après les ingrédients
        instructions = st.text_area(
            "Étapes de préparation",
            placeholder="Ex.: 1) Mélanger... 2) Cuire... 3) Dresser...",
            height=140,
        )

        if st.button("Enregistrer la recette + ingrédients"):
            if not name.strip():
                st.warning("Nom requis.")
            else:
                try:
                    # 1) Upsert recette
                    r = db.query(Recipe).filter(Recipe.name.ilike(name.strip())).first()
                    if not r:
                        r = Recipe(
                            name=name.strip(),
                            servings=int(servings),
                            category=(category or "Général").strip(),
                            instructions=(instructions or "").strip(),
                        )
                        db.add(r)
                        db.commit()
                        db.refresh(r)
                    else:
                        r.servings = int(servings)
                        r.category = (category or "Général").strip()
                        r.instructions = (instructions or "").strip()
                        db.commit()

                    # 2) Enregistrer lignes d'ingrédients du tableau
                    rows_ok = 0
                    for _, row in df_edit.iterrows():
                        label = (row.get("Ingredient") or "").strip()
                        if not label:
                            continue
                        qty = float(row.get("Quantite") or 0)
                        if qty <= 0:
                            continue
                        unit = (row.get("Unite") or "").strip()
                        ing_id = label_to_id.get(label)
                        if not ing_id:
                            continue

                        base = id_to_base.get(ing_id, "g")
                        allowed = _unit_choices(base)
                        if unit not in allowed:
                            st.warning(
                                f"Ingrédient {label}: unité '{unit}' non compatible avec base '{base}'. "
                                f"Utilisez: {', '.join(allowed)}"
                            )
                            continue

                        it = (
                            db.query(RecipeItem)
                            .filter(RecipeItem.recipe_id == r.id, RecipeItem.ingredient_id == ing_id)
                            .first()
                        )
                        if it:
                            it.quantity = qty
                            it.unit = normalize_unit(unit)
                        else:
                            db.add(
                                RecipeItem(
                                    recipe_id=r.id,
                                    ingredient_id=ing_id,
                                    quantity=qty,
                                    unit=normalize_unit(unit),
                                )
                            )
                        rows_ok += 1

                    db.commit()
                    st.success(f"Recette et ingrédients enregistrés (lignes valides: {rows_ok}).")
                    st.session_state[grid_key] = _empty_grid_df(3)
                    _rerun()

                except Exception as e:
                    st.error(f"Erreur lors de l'enregistrement: {e}")

    st.divider()

    # ------------------------------------------------------------------
    # 2) SÉLECTION D'UNE RECETTE EXISTANTE ET INGREDIENTS
    # ------------------------------------------------------------------
    recipes = db.query(Recipe).order_by(Recipe.name).all()
    if not recipes:
        st.info("Aucune recette en base pour le moment.")
        return

    sel_name = st.selectbox("Sélectionner une recette", [r.name for r in recipes])
    recipe: Recipe = db.query(Recipe).filter(Recipe.name == sel_name).first()

    st.subheader(f"Ingrédients — {recipe.name}")
    items = db.query(RecipeItem).filter(RecipeItem.recipe_id == recipe.id).all()
    rows = []
    for it in items:
        rows.append(
            {
                "Ingrédient": it.ingredient.name,
                "Quantité": it.quantity,
                "Unité": it.unit,
                "Fournisseur": (it.ingredient.supplier.name if it.ingredient.supplier else ""),
                "Prix base ($/unité)": round(it.ingredient.price_per_base_unit, 6),
            }
        )
    df_items = pd.DataFrame(rows)
    if not df_items.empty:
        st.dataframe(
            df_items.style.format({"Quantité": "{:.2f}", "Prix base ($/unité)": "{:.4f}"}),
            use_container_width=True,
        )
    else:
        st.info("Aucun ingrédient ajouté pour cette recette pour l'instant.")

    # Suppression d'un ingrédient
    with st.popover("🗑️ Retirer un ingrédient"):
        if items:
            sel = st.selectbox("Choisir un ingrédient", [it.ingredient.name for it in items])
            if st.button("Retirer"):
                tgt = next((it for it in items if it.ingredient.name == sel), None)
                if tgt:
                    db.delete(tgt)
                    db.commit()
                    st.success("Ingrédient retiré.")
                    _rerun()

    # ------------------------------------------------------------------
    # 3) ÉTAPES DE PRÉPARATION (édition + aperçu)
    # ------------------------------------------------------------------
    st.subheader("Étapes de préparation")
    edited = st.text_area(
        "Modifier les étapes",
        value=(recipe.instructions or ""),
        height=200,
        placeholder="Ex.: 1) Mélanger la farine et le lait...\n2) Ajouter les œufs...\n3) Cuire 2 min de chaque côté...",
    )
    if st.button("Enregistrer les étapes (recette sélectionnée)"):
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
    # 4) EXPORT PDF
    # ------------------------------------------------------------------
    pdf_items = []
    for it in items:
        pdf_items.append(
            (
                it.ingredient.name,
                float(it.quantity or 0),
                it.unit or "",
                (it.ingredient.supplier.name if it.ingredient.supplier else ""),
                float(it.ingredient.price_per_base_unit or 0.0),
            )
        )

    try:
        cost_vals = recipe_cost(db, recipe.id)
        total_cost = float(cost_vals.get("total_cost", 0.0))
        per_serv = float(cost_vals.get("per_serving", 0.0))
    except Exception:
        total_cost, per_serv = 0.0, 0.0

    pdf_bytes = build_recipe_pdf(
        recipe_name=recipe.name,
        category=recipe.category or "Général",
        servings=int(recipe.servings or 1),
        items=pdf_items,
        instructions=recipe.instructions or "",
        cost_total=total_cost,
        cost_per_serving=per_serv,
    )

    st.download_button(
        label="📄 Exporter la fiche recette (PDF)",
        data=pdf_bytes,
        file_name=f"Fiche_{recipe.name.replace(' ', '_')}.pdf",
        mime="application/pdf",
        use_container_width=True,
    )

    # ------------------------------------------------------------------
    # 5) COÛTS
    # ------------------------------------------------------------------
    st.subheader("Coûts")
    try:
        cost = recipe_cost(db, recipe.id)
        c1, c2 = st.columns(2)
        c1.metric("Coût total de la recette ($)", f"{cost['total_cost']:.2f}")
        c2.metric("Coût par portion ($)", f"{cost['per_serving']:.2f}")
    except Exception as e:
        st.error(f"Impossible de calculer les coûts: {e}")
