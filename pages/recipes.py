import streamlit as st
import pandas as pd
from sqlalchemy.orm import Session
from sqlalchemy import select
from db import Recipe, Ingredient, RecipeItem
from pages.logic import recipe_cost
from units import normalize_unit


# -------- helpers --------
def _rerun():
    try:
        st.rerun()
    except AttributeError:
        # compat anciennes versions streamlit
        st.experimental_rerun()


def _unit_choices(base_unit: str):
    if base_unit == "g":
        return ["mg", "g", "kg"]
    if base_unit == "ml":
        return ["ml", "l"]
    return ["unit"]


def _init_recipe_grid_state(key: str, rows: int = 3):
    if key not in st.session_state:
        st.session_state[key] = pd.DataFrame(
            [{"Ingredient": "", "Quantite": 0.0, "Unite": ""} for _ in range(rows)]
        )


def recipes_page(db: Session) -> None:
    st.header("Recettes")

    # ------------------------------------------------------------
    # Creer / modifier une recette (inclut instructions)
    # ------------------------------------------------------------
    with st.expander("Creer ou modifier une recette", expanded=True):
        colA, colB = st.columns([2, 1])
        name = colA.text_input("Nom de la recette *")
        servings = colB.number_input("Nombre de portions", min_value=1, value=1)
        category = st.text_input("Categorie", value="General")

        instructions = st.text_area(
            "Etapes de preparation",
            placeholder="Decrivez les etapes (ex. 1) Melanger... 2) Cuire... 3) Dresser...)",
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
                        instructions=(instructions or "").strip(),
                    )
                    db.add(r)
                else:
                    r.servings = int(servings)
                    r.category = category.strip() or "General"
                    r.instructions = (instructions or "").strip()
                db.commit()
                st.success(f"Recette enregistree : {r.name}")

    st.divider()

    # ------------------------------------------------------------
    # Selection recette
    # ------------------------------------------------------------
    recipes = db.query(Recipe).order_by(Recipe.name).all()
    if not recipes:
        st.info("Creez d'abord une recette ci-dessus.")
        return

    sel_name = st.selectbox("Selectionner une recette", [r.name for r in recipes])
    recipe: Recipe = db.query(Recipe).filter(Recipe.name == sel_name).first()

    # ------------------------------------------------------------
    # Chargement ingredients disponibles (pour menus deroulants)
    # ------------------------------------------------------------
    ing_rows = db.execute(select(Ingredient.id, Ingredient.name, Ingredient.category, Ingredient.base_unit)
                          .order_by(Ingredient.name)).all()
    # tuples (id, name, category, base_unit)
    if not ing_rows:
        st.warning("Aucun ingredient dans le catalogue. Ajoutez-en d'abord dans Ingrédients.")
        return

    # etiquettes visibles et mappings
    labels = []
    label_to_id = {}
    id_to_base = {}
    for ing_id, ing_name, ing_cat, base in ing_rows:
        label = f"{ing_name} ({ing_cat or 'Autre'})"
        labels.append(label)
        label_to_id[label] = ing_id
        id_to_base[ing_id] = base

    # ------------------------------------------------------------
    # Tableau editable: ajout multiple d'ingredients pour la recette
    # ------------------------------------------------------------
    st.subheader(f"Ingredients — {recipe.name}")

    grid_key = f"recipe_grid_{recipe.id}"
    _init_recipe_grid_state(grid_key, rows=3)

    st.caption("Ajouter plusieurs ingredients (une ligne par ingredient). "
               "Choisissez l'ingredient, saisissez la quantite, puis l'unite.")

    add_cols = st.columns([1, 1, 2])
    add_n = add_cols[0].number_input("Ajouter lignes", min_value=1, max_value=20, value=3, step=1)
    if add_cols[1].button("Ajouter"):
        df0 = st.session_state[grid_key]
        more = pd.DataFrame([{"Ingredient": "", "Quantite": 0.0, "Unite": ""} for _ in range(int(add_n))])
        st.session_state[grid_key] = pd.concat([df0, more], ignore_index=True)

    # configuration du data_editor
    df_edit = st.data_editor(
        st.session_state[grid_key],
        key=f"editor_{recipe.id}",
        num_rows="dynamic",
        hide_index=True,
        use_container_width=True,
        column_config={
            "Ingredient": st.column_config.SelectboxColumn(
                "Ingredient",
                help="Choisir un ingredient du catalogue",
                options=[""] + labels,
                required=False,
            ),
            "Quantite": st.column_config.NumberColumn(
                "Quantite",
                help="Quantite utilisee pour la recette",
                min_value=0.0,
                step=1.0,
                format="%.2f",
            ),
            "Unite": st.column_config.SelectboxColumn(
                "Unite",
                help="Unite de la quantite saisie (compatible avec l'unite de base de l'ingredient)",
                options=["", "mg", "g", "kg", "ml", "l", "unit"],
                required=False,
            ),
        },
    )

    # bouton d'enregistrement en lot
    if st.button("Enregistrer les ingredients ajoutes/updates"):
        try:
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

                # valider compatibilite unite
                base = id_to_base.get(ing_id, "g")
                allowed = _unit_choices(base)
                if unit not in allowed:
                    st.warning(f"Ingr {label}: unite '{unit}' non compatible avec base '{base}'. "
                               f"Utilisez: {', '.join(allowed)}")
                    continue

                # upsert RecipeItem
                it = (
                    db.query(RecipeItem)
                    .filter(RecipeItem.recipe_id == recipe.id, RecipeItem.ingredient_id == ing_id)
                    .first()
                )
                if it:
                    it.quantity = qty
                    it.unit = normalize_unit(unit)
                else:
                    db.add(RecipeItem(
                        recipe_id=recipe.id,
                        ingredient_id=ing_id,
                        quantity=qty,
                        unit=normalize_unit(unit),
                    ))
                rows_ok += 1

            db.commit()
            if rows_ok:
                st.success(f"{rows_ok} ligne(s) enregistree(s).")
            else:
                st.info("Aucune ligne valide a enregistrer.")
            _rerun()
        except Exception as e:
            st.error(f"Erreur lors de l'enregistrement: {e}")

    # ------------------------------------------------------------
    # Tableau des ingredients deja associes a la recette
    # ------------------------------------------------------------
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
    df_items = pd.DataFrame(rows)
    if not df_items.empty:
        st.dataframe(
            df_items.style.format({
                "Quantite": "{:.2f}",
                "Prix base ($/unite)": "{:.4f}",
            }),
            use_container_width=True
        )
    else:
        st.info("Aucun ingredient ajoute pour cette recette pour l'instant.")

    # suppression d'un ingredient
    with st.popover("Retirer un ingredient"):
        if items:
            sel = st.selectbox("Choisir un ingredient", [it.ingredient.name for it in items])
            if st.button("Retirer"):
                tgt = next((it for it in items if it.ingredient.name == sel), None)
                if tgt:
                    db.delete(tgt)
                    db.commit()
                    st.success("Ingredient retire.")
                    _rerun()

    # ------------------------------------------------------------
    # Etapes de preparation (edition + apercu)
    # ------------------------------------------------------------
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

    st.caption("Apercu (numerote)")
    preview = [ln.strip() for ln in (edited or "").splitlines() if ln.strip()]
    if preview:
        st.markdown("\n".join([f"{i+1}. {line}" for i, line in enumerate(preview)]))
    else:
        st.write("_Aucune etape pour le moment._")

    # ------------------------------------------------------------
    # Couts
    # ------------------------------------------------------------
    st.subheader("Couts")
    try:
        cost = recipe_cost(db, recipe.id)
        c1, c2 = st.columns(2)
        c1.metric("Cout total de la recette ($)", f"{cost['total_cost']:.2f}")
        c2.metric("Cout par portion ($)", f"{cost['per_serving']:.2f}")
    except Exception as e:
        st.error(f"Impossible de calculer les couts: {e}")
