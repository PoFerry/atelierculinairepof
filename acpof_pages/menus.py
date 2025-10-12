import streamlit as st
import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session
from db import Menu, MenuItem, Recipe, RecipeItem, Ingredient
from units import to_base_units, normalize_unit

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
    """Affiche joliment une quantité en unités 'humaines' (kg/l si grand)."""
    if base_unit == "g":
        if qty >= 1000:
            return qty / 1000.0, "kg"
        return qty, "g"
    if base_unit == "ml":
        if qty >= 1000:
            return qty / 1000.0, "l"
        return qty, "ml"
    return qty, "unit"


def _menu_creator_table(recipes: list[Recipe]) -> pd.DataFrame:
    """Table éditable pour saisir les PORTIONS par recette lors de la création du menu."""
    return pd.DataFrame(
        [{"Recette": r.name, "Portions": int(r.servings or 1)} for r in recipes]
    )


def menus_page(db: Session):
    st.header("Menus")

    # ------------------------------------------------------------------
    # 1) Créer / modifier un menu (sélection multiple + PORTIONS par recette)
    # ------------------------------------------------------------------
    with st.expander("Créer ou modifier un menu", expanded=True):
        name = st.text_input("Nom du menu *", placeholder="Ex. Menu d'automne")
        notes = st.text_area("Notes (optionnel)", placeholder="Détails logistiques, allergènes, etc.")

        # Multisélection des recettes existantes
        all_recipes = db.execute(select(Recipe).order_by(Recipe.name)).scalars().all()
        recipe_labels = [r.name for r in all_recipes]
        selected_labels = st.multiselect(
            "Recettes à inclure",
            recipe_labels,
            help="Sélectionnez une ou plusieurs recettes"
        )

        # Tableau des PORTIONS par recette sélectionnée
        selected_recipes = [r for r in all_recipes if r.name in selected_labels]
        if selected_recipes:
            st.caption("Indique le NOMBRE DE PORTIONS souhaitées pour chaque recette du menu.")
            df_init = _menu_creator_table(selected_recipes)
            df_portions = st.data_editor(
                df_init,
                key="menu_creator_editor",
                hide_index=True,
                use_container_width=True,
                column_config={
                    "Recette": st.column_config.TextColumn("Recette", disabled=True),
                    "Portions": st.column_config.NumberColumn(
                        "Portions", min_value=0, step=1, format="%d"
                    ),
                },
            )
        else:
            df_portions = None

        if st.button("Enregistrer le menu"):
            if not name.strip():
                st.warning("Le nom du menu est requis.")
            else:
                try:
                    # Upsert Menu
                    menu = db.query(Menu).filter(Menu.name.ilike(name.strip())).first()
                    if not menu:
                        menu = Menu(name=name.strip())
                        db.add(menu)
                        db.commit()
                        db.refresh(menu)
                    # notes si dispo
                    if hasattr(menu, "notes"):
                        menu.notes = (notes or "").strip()

                    # Vider les liens existants
                    db.query(MenuItem).filter(MenuItem.menu_id == menu.id).delete()

                    # Recréer les liens avec conversion portions -> batches
                    if df_portions is not None and not df_portions.empty:
                        cnt = 0
                        for _, row in df_portions.iterrows():
                            rname = str(row.get("Recette") or "").strip()
                            portions = float(row.get("Portions") or 0)
                            if not rname or portions <= 0:
                                continue
                            rec = next((r for r in all_recipes if r.name == rname), None)
                            if not rec:
                                continue
                            base_serv = float(rec.servings or 1)
                            batches = portions / base_serv
                            db.add(MenuItem(menu_id=menu.id, recipe_id=rec.id, batches=batches))
                            cnt += 1

                    db.commit()
                    # synchro
                    auto_export(db, "menus")
                    auto_export(db, "menu_items")

                    st.success(f"Menu « {menu.name} » enregistré.")
                    _rerun()

                except Exception as e:
                    st.error(f"Erreur lors de l'enregistrement du menu: {e}")

    st.divider()

    # ------------------------------------------------------------------
    # 2) Sélection d’un menu existant + affichage des recettes & portions
    # ------------------------------------------------------------------
    menus = db.query(Menu).order_by(Menu.name).all()
    if not menus:
        st.info("Aucun menu enregistré pour le moment.")
        return

    menu_name = st.selectbox("Sélectionner un menu", [m.name for m in menus])
    menu = db.query(Menu).filter(Menu.name == menu_name).first()

    # Récupération des items (batches) et calcul des PORTIONS stockées (portions = batches * servings)
    links = db.query(MenuItem).filter(MenuItem.menu_id == menu.id).all()
    if not links:
        st.info("Aucune recette associée à ce menu.")
    else:
        rows = []
        for l in links:
            rec = l.recipe
            servings = float(rec.servings or 1)
            portions = l.batches * servings
            rows.append({
                "Recette": rec.name,
                "Catégorie": rec.category or "",
                "Portions": int(round(portions)),
                "Batches (xRecette)": round(l.batches, 3),
            })
        st.subheader(f"Recettes du menu — {menu.name}")
        st.dataframe(pd.DataFrame(rows), hide_index=True, use_container_width=True)

    # ------------------------------------------------------------------
    # 3) Liste des besoins (achats) agrégée pour le menu sélectionné
    # ------------------------------------------------------------------
    st.subheader("Liste des besoins (agrégée)")
    if not links:
        st.info("Aucune recette → pas de besoins.")
        return

    needs = {}  # ingredient_id -> agg
    for l in links:
        rec = l.recipe
        factor = float(l.batches or 0.0)
        if factor <= 0:
            continue

        recipe_items = db.query(RecipeItem).filter(RecipeItem.recipe_id == rec.id).all()
        for it in recipe_items:
            ing: Ingredient = it.ingredient
            qty = float(it.quantity or 0.0)
            unit = normalize_unit(it.unit or ing.base_unit or "g")
            if qty <= 0:
                continue
            try:
                base_qty = to_base_units(qty, unit, ing.base_unit or "g")
            except Exception:
                continue

            total_add = base_qty * factor
            if ing.id not in needs:
                needs[ing.id] = {
                    "name": ing.name,
                    "base_unit": ing.base_unit,
                    "total_base": 0.0,
                    "supplier": (ing.supplier.name if ing.supplier else ""),
                    "category": (ing.category or ""),
                }
            needs[ing.id]["total_base"] += total_add

    if not needs:
        st.info("Aucun besoin calculable (vérifier unités/quantités).")
        return

    out_rows = []
    for _, info in sorted(needs.items(), key=lambda x: x[1]["name"].lower()):
        qty_base = info["total_base"]
        disp_qty, disp_unit = _pretty_qty(info["base_unit"], qty_base)
        out_rows.append({
            "Ingrédient": info["name"],
            "Catégorie": info["category"],
            "Fournisseur": info["supplier"],
            "Quantité totale": round(disp_qty, 3),
            "Unité": disp_unit,
        })
    df_needs = pd.DataFrame(out_rows)
    st.dataframe(df_needs, hide_index=True, use_container_width=True)

    # Export CSV des besoins
    csv = df_needs.to_csv(index=False).encode("utf-8")
    st.download_button(
        label="📥 Exporter la liste des besoins (CSV)",
        data=csv,
        file_name=f"Liste_besoins_{menu.name.replace(' ', '_')}.csv",
        mime="text/csv",
        use_container_width=True,
    )

    # ------------------------------------------------------------------
    # 4) Suppression du menu
    # ------------------------------------------------------------------
    with st.popover("🗑️ Supprimer ce menu"):
        if st.button(f"Supprimer définitivement « {menu.name} »"):
            db.delete(menu)
            db.commit()
            auto_export(db, "menus")
            auto_export(db, "menu_items")
            st.success("Menu supprimé.")
            _rerun()
