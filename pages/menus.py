import streamlit as st
import pandas as pd
from sqlalchemy.orm import Session
from db import Menu, MenuItem, Recipe
from logic import menu_aggregate_needs
from export_utils import export_csv

def menus_page(db: Session):
    st.header("Menus")
    with st.expander("➕ Créer / Renommer un menu", expanded=True):
        name = st.text_input("Nom du menu *")
        if st.button("Enregistrer le menu"):
            if not name.strip():
                st.error("Le nom est requis.")
            else:
                existing = db.query(Menu).filter(Menu.name.ilike(name.strip())).first()
                if existing:
                    st.success(f"Menu déjà existant: {existing.name}")
                else:
                    m = Menu(name=name.strip()); db.add(m); db.commit(); st.success(f"Menu créé: {m.name}")

    menus = db.query(Menu).order_by(Menu.name).all()
    if not menus:
        st.info("Créez d'abord un menu."); return

    sel = st.selectbox("Sélectionner un menu", [m.name for m in menus])
    menu = db.query(Menu).filter(Menu.name == sel).first()

    st.subheader("Recettes dans le menu")
    recipes = db.query(Recipe).order_by(Recipe.name).all()
    rec_map = {r.name: r for r in recipes}
    with st.popover("➕ Ajouter une recette au menu"):
        rec_name = st.selectbox("Recette", list(rec_map.keys()))
        batches = st.number_input("Nombre de fois que la recette est réalisée", min_value=0.1, value=1.0, step=0.5)
        if st.button("Ajouter au menu"):
            r = rec_map[rec_name]
            existing = db.query(MenuItem).filter(MenuItem.menu_id==menu.id, MenuItem.recipe_id==r.id).first()
            if existing: existing.batches = float(batches)
            else: db.add(MenuItem(menu_id=menu.id, recipe_id=r.id, batches=float(batches)))
            db.commit(); st.success("Recette ajoutée/mise à jour."); st.experimental_rerun()

    items = db.query(MenuItem).filter(MenuItem.menu_id == menu.id).all()
    if items:
        st.dataframe(pd.DataFrame([{"Recette": it.recipe.name, "Batches": it.batches} for it in items]), use_container_width=True)

    st.subheader("Liste d'achats / Besoins en ingrédients (agrégé)")
    needs = menu_aggregate_needs(db, menu.id)
    rows = []
    for _, rec in needs.items():
        rows.append({"Ingrédient": rec["name"], "Quantité (base)": round(rec["total_qty_base"], 3), "Unité": rec["base_unit"], "Fournisseur": rec.get("supplier","")})
    df = pd.DataFrame(rows).sort_values("Ingrédient")
    st.dataframe(df, use_container_width=True)

    if not df.empty and st.button("📤 Exporter la liste d'achats (CSV)"):
        path = export_csv(df, prefix=f"liste_achats_{menu.name}")
        st.success(f"Export CSV créé: {path}")
        st.download_button("Télécharger le CSV", data=open(path,"rb").read(), file_name=path.split("/")[-1], mime="text/csv")

    with st.popover("🗑️ Retirer une recette du menu"):
        if items:
            selr = st.selectbox("Choisir", [it.recipe.name for it in items])
            if st.button("Retirer"):
                tgt = next((it for it in items if it.recipe.name == selr), None)
                if tgt: db.delete(tgt); db.commit(); st.success("Recette retirée du menu."); st.experimental_rerun()
