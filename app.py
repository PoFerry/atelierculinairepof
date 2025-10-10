import streamlit as st
from db import init_db, SessionLocal
from pages.ingredients import ingredients_page
from pages.recipes import recipes_page
from pages.menus import menus_page

st.set_page_config(page_title="Atelier Culinaire POF — App 2.0 (améliorée)", layout="wide")
init_db()
PAGES = {"Ingrédients": ingredients_page, "Recettes": recipes_page, "Menus": menus_page}
st.sidebar.title("Navigation")
choice = st.sidebar.radio("Aller à…", list(PAGES.keys()))
with SessionLocal() as db:
    PAGES[choice](db)
