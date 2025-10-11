# app.py
from __future__ import annotations

import base64
from pathlib import Path

import streamlit as st

from db import init_db, SessionLocal
from pages.ingredients import ingredients_page
from pages.recipes import recipes_page
from pages.menus import menus_page
from pages.suppliers import suppliers_page
from pages.inventory import inventory_page


# -----------------------------
#  UI helpers (branding & style)
# -----------------------------
APP_DIR = Path(__file__).parent
LOGO_PATHS = [
    APP_DIR / "Logo_atelierPOF.png",
    APP_DIR / "logo_atelierpof.png",
    APP_DIR / "assets" / "Logo_atelierPOF.png",
]


def _get_logo_bytes():
    for p in LOGO_PATHS:
        if p.exists():
            return p.read_bytes()
    return None


def add_logo():
    """Affiche le logo et l’entête de marque en haut de la page (base64 inline)."""
    data = _get_logo_bytes()
    if not data:
        st.markdown(
            "<h1 style='text-align:center; margin-top:-20px;'>Atelier Culinaire — POF</h1>",
            unsafe_allow_html=True,
        )
        return
    encoded = base64.b64encode(data).decode()
    st.markdown(
        f"""
        <div style="text-align:center; margin-top:-30px; margin-bottom:10px;">
            <img src="data:image/png;base64,{encoded}" width="140" alt="Atelier Culinaire POF"/>
            <h1 style="margin:8px 0 0 0; font-weight:600; letter-spacing:0.5px; color:#2f3a3a;">
                Atelier Culinaire
            </h1>
            <div style="margin-top:2px; color:#596066; font-size:16px; letter-spacing:0.5px;">
                <b>Pierre-Olivier Ferry</b>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def set_custom_style():
    """Injecte un thème léger cohérent avec le logo (vert sauge)."""
    st.markdown(
        """
        <style>
        :root {
            --pof-green: #A7B97A;   /* vert sauge du logo */
            --pof-ink:   #2f3a3a;   /* texte foncé doux */
            --pof-soft:  #EEF0EA;   /* fond sidebar */
            --pof-bg:    #FAFAF7;   /* fond app */
        }
        .stApp { background-color: var(--pof-bg); }
        h1, h2, h3, h4 { color: var(--pof-ink); }

        section[data-testid="stSidebar"] {
            background-color: var(--pof-soft);
            border-right: 1px solid rgba(0,0,0,0.05);
        }

        button[kind="primary"] {
            background-color: var(--pof-green) !important;
            color: #fff !important;
            border-radius: 8px !important;
            border: none !important;
        }
        div[data-testid="stExpander"] { border-radius: 10px; }
        .stDataFrame { border-radius: 10px; overflow: hidden; }
        div[data-testid="stMetric"] {
            background: white; border: 1px solid #ebede8; border-radius: 12px;
            padding: 10px 14px;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def sidebar_branding():
    """Logo en sidebar, avec fallback si le fichier est introuvable."""
    data = _get_logo_bytes()
    if data:
        st.sidebar.image(data, width=110, caption="")
    else:
        st.sidebar.write("Atelier Culinaire — POF")
    st.sidebar.markdown("—")
    st.sidebar.caption("Atelier Culinaire • P.-O. Ferry")
    st.sidebar.markdown("—")


# -----------------------------
#  Pages
# -----------------------------
def home_page():
    st.subheader("Bienvenue 👋")
    st.write(
        """
        Cette application vous permet de gérer **ingrédients**, **recettes**, **menus** et
        **inventaire**, avec export **CSV/PDF**.

        **Par où commencer ?**
        1. Allez dans **Ingrédients** pour créer votre catalogue (format d’achat, prix, fournisseur).
        2. Créez des **Recettes**, ajoutez les ingrédients et visualisez le **coût par portion**.
        3. Composez vos **Menus** et obtenez la **liste d’achats agrégée** (CSV ou PDF).
        4. Utilisez **Inventaire** pour enregistrer les **entrées/sorties** (stock actuel calculé).
        """
    )
    st.info(
        "Astuce : vous pouvez rester en **SQLite** pendant la mise au point, "
        "et passer à **Supabase (Postgres)** plus tard sans changer vos écrans."
    )


# -----------------------------
#  App
# -----------------------------
st.set_page_config(
    page_title="Atelier Culinaire POF — App 2.0",
    page_icon="🍃",
    layout="wide",
)

set_custom_style()
add_logo()
init_db()

PAGES = {
    "🏠 Accueil": home_page,
    "🥕 Ingrédients": ingredients_page,
    "🧾 Recettes": recipes_page,
    "📋 Menus": menus_page,
    "🏷️ Fournisseurs": suppliers_page,
    "📦 Inventaire": inventory_page,
}

sidebar_branding()
choice = st.sidebar.radio("Navigation", list(PAGES.keys()), index=0, label_visibility="visible")

with SessionLocal() as db:
    if choice == "🏠 Accueil":
        PAGES[choice]()  # home_page sans session
    else:
        PAGES[choice](db)
