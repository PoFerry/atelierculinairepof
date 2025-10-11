import streamlit as st
import pandas as pd
from sqlalchemy.orm import Session
from db import Menu, MenuItem, Recipe
from pages.logic import menu_aggregate_needs

def menus_page(db: Session):
    st.header("Menus")

    with st.expander("➕ Créer un menu", expanded=True):
        name = st.text_input("Nom du menu")
        if st.button("Créer"):
            if not name.strip():
                st.warning("Nom requis.")
            else:
                m = db.query(Menu).filter(Menu.name.ilike(name.strip())).first()
                if not m:
                    m = Menu(name=name.strip())
                    db.add(m)
                    db.commit()
                    st.success(f"Menu créé : {m.name}")
                else:
                    st.info("Ce menu existe déjà.")

    menus = db.query(Menu).order_by(Menu.name).all()
    st.subheader("📋 Liste des menus")
    st.dataframe(pd.DataFrame([{"Nom": m.name} for m in menus]), use_container_width=True)

    st.divider()
    sel = st.selectbox("Choisir un menu :", [m.name for m in menus] if menus else [])
    if sel:
        m = db.query(Menu).filter(Menu.name == sel).first()
        st.subheader(f"Menu : {m.name}")

        recipes = db.query(Recipe).order_by(Recipe.name).all()
        r_map = {r.name: r for r in recipes}
        sel_recipe = st.selectbox("Ajouter une recette :", list(r_map.keys()))
        qty = st.number_input("Nombre de fois cette recette", min_value=0.1, value=1.0, step=0.1)
        if st.button("Ajouter au menu"):
            mi = MenuItem(menu_id=m.id, recipe_id=r_map[sel_recipe].id, batches=qty)
            db.add(mi)
            db.commit()
            st.success("Ajouté au menu.")
            st.rerun()

        # afficher besoins agrégés
        st.subheader("🧾 Besoins agrégés du menu")
        needs = menu_aggregate_needs(db, m.id)
        df = pd.DataFrame(list(needs.values()))
        st.dataframe(df, use_container_width=True)
