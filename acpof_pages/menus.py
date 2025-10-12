import streamlit as st
import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session
from db import Menu, MenuItem, Recipe, RecipeItem, Ingredient
from units import to_base_units, normalize_unit
from sheets_sync import auto_export

# ... après db.commit() réussi
auto_export(db, "menus")
auto_export(db, "menu_items")

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
    # unit (pièce)
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
                        st.success("menu enregistré.")
                        auto_export(db, "menus")
                        db.refresh(menu)
                    # notes (si le champ existe dans ton modèle)
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
                            batches = portions / base_serv  # <-- conversion clé
                            db.add(MenuItem(menu_id=menu.id, recipe_id=rec.id, batches=batches))
                            cnt += 1
                        db.commit()
                        st.success("Menu enregistré.")
                        auto_export(db, "menus")
                    else:
                        st.info("Menu enregistré sans recettes.")
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

    # Agrégation : somme des ingrédients requis pour chaque recette * batches
    # On convertit chaque quantité d'item de recette vers l'unité de base de l'ingrédient.
    needs = {}  # key: ingredient_id -> {"name":..., "base_unit":..., "total_base": float, "supplier": str}
    for l in links:
        rec = l.recipe
        factor = float(l.batches or 0.0)  # multiplier toutes les quantités de la recette
        if factor <= 0:
            continue

        recipe_items = db.query(RecipeItem).filter(RecipeItem.recipe_id == rec.id).all()
        for it in recipe_items:
            ing: Ingredient = it.ingredient
            qty = float(it.quantity or 0.0)
            unit = normalize_unit(it.unit or ing.base_unit or "g")
            if qty <= 0:
                continue

            # convertir vers unité de base de l'ingrédient
            try:
                base_qty = to_base_units(qty, unit, ing.base_unit or "g")
            except Exception:
                # si conversion impossible (mauvaise unité), on ignore cette ligne
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

    # Préparer DataFrame d'affichage (joli)
    out_rows = []
    for ing_id, info in sorted(needs.items(), key=lambda x: x[1]["name"].lower()):
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

    # Optionnel : export CSV des besoins
    csv = df_needs.to_csv(index=False).encode("utf-8")
    st.download_button(
        label="📥 Exporter la liste des besoins (CSV)",
        data=csv,
        file_name=f"Liste_besoins_{menu.name.replace(' ', '_')}.csv",
        mime="text/csv",
        use_container_width=True,
    )
# --- Synchronisation Google Sheets ---
from sheets_sync import export_all_tables, import_all_tables

def _sync_panel(db):
    st.divider()
    st.subheader("📤 Synchronisation Google Sheets")

    c1, c2 = st.columns(2)
    with c1:
        if st.button("Exporter toutes les tables → Sheets", use_container_width=True):
            res = export_all_tables(db)
            ok = {k: v for k, v in res.items() if v >= 0}
            ko = {k: v for k, v in res.items() if v < 0}
            st.success(f"Export terminé. OK : {list(ok.keys())}")
            if ko:
                st.warning(f"Échecs : {list(ko.keys())}")

    with c2:
        if st.button("Importer depuis Sheets → DB (REMPLACE)", use_container_width=True):
            res = import_all_tables(db)
            ok = {k: v for k, v in res.items() if v >= 0}
            ko = {k: v for k, v in res.items() if v < 0}
            st.success(f"Import terminé. OK : {list(ok.keys())}")
            if ko:
                st.warning(f"Échecs : {list(ko.keys())}")
            st.rerun()

    # ------------------------------------------------------------------
    # 4) Suppression du menu
    # ------------------------------------------------------------------
    with st.popover("🗑️ Supprimer ce menu"):
        if st.button(f"Supprimer définitivement « {menu.name} »"):
            db.delete(menu)
            db.commit()
            st.success("Menu supprimé.")
            auto_export(db, "menu_items")
            
            _rerun()
