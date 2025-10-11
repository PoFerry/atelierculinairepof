# app.py (extraits principaux)

import streamlit as st
from pathlib import Path
from db import init_db, SessionLocal
# pages
from pages.ingredients import ingredients_page
from pages.recipes import recipes_page
from pages.menus import menus_page
from pages.suppliers import suppliers_page
from pages.inventory import inventory_page

st.set_page_config(
    page_title="Atelier Culinaire POF",
    page_icon="🍽️",
    layout="wide",
    initial_sidebar_state="expanded",
)

APP_DIR = Path(__file__).parent
LOGO_PATHS = [
    APP_DIR / "Logo_atelierPOF.png",
    APP_DIR / "logo_atelierpof.png",
    APP_DIR / "assets" / "Logo_atelierPOF.png",
]

def _logo_path():
    for p in LOGO_PATHS:
        if p.exists():
            return str(p)
    return None

# --- petit CSS pour la sidebar ---
st.markdown("""
<style>
/* fond + typographie sidebar */
section[data-testid="stSidebar"] {
  background: #0f172a; /* slate-900 */
  color: #e5e7eb;      /* gray-200 */
}
section[data-testid="stSidebar"] * {
  color: #e5e7eb;
}

/* boutons radio plus élégants */
div[role="radiogroup"] > label {
  padding: 10px 12px;
  border-radius: 10px;
  margin-bottom: 6px;
  border: 1px solid rgba(255,255,255,0.08);
  background: rgba(255,255,255,0.03);
}
div[role="radiogroup"] > label:hover {
  border-color: rgba(255,255,255,0.25);
  background: rgba(255,255,255,0.06);
}

/* titre / caption */
.sidebar-title {
  font-weight: 700; letter-spacing:.3px; font-size: 0.9rem; color:#cbd5e1; /* slate-300 */
  margin: 6px 0 4px 0;
}

/* badge arrondi */
.badge {
  display:inline-block; padding:2px 8px; border-radius:9999px;
  background:#1e293b; color:#cbd5e1; font-size:12px; border:1px solid rgba(255,255,255,0.08);
  margin-left: 8px;
}

/* masquer le hamburger + footer streamlit si tu veux encore plus clean */
/*
button[kind="header"] {visibility:hidden;}
footer {visibility:hidden;}
*/
</style>
""", unsafe_allow_html=True)

def sidebar_branding():
    logo = _logo_path()
    if logo:
        st.sidebar.image(logo, use_column_width=True)
    st.sidebar.markdown('<div class="sidebar-title">Navigation</div>', unsafe_allow_html=True)

def get_counts(db):
    # evite les imports circulaires
    from db import Ingredient, Recipe, Menu
    return (
        db.query(Ingredient).count(),
        db.query(Recipe).count(),
        db.query(Menu).count()
    )

def main():
    init_db()
    db = SessionLocal()

    # --- Branding + métriques ---
    sidebar_branding()
    ing_count, rec_count, menu_count = get_counts(db)

    # dictionnaire de pages: pas de doublons
    PAGES = {
        "🏠 Accueil": None,           # optionnel si tu as une page home
        f"🧂 Ingrédients  <span class='badge'>{ing_count}</span>": ingredients_page,
        f"📖 Recettes  <span class='badge'>{rec_count}</span>": recipes_page,
        f"🗂️ Menus  <span class='badge'>{menu_count}</span>": menus_page,
        "🏷️ Fournisseurs": suppliers_page,
        "📦 Inventaire": inventory_page,
    }

    # affichage radio avec HTML autorisé (formatage badges)
    choice = st.sidebar.radio(
        label="",
        options=list(PAGES.keys()),
        index=1 if "Ingrédients" in list(PAGES.keys())[1] else 0,
        key="nav_choice",
    )

    # petit séparateur
    st.sidebar.markdown("---")
    st.sidebar.caption("Atelier Culinaire Pierre-Olivier Ferry")

    # router
    page_fn = PAGES[choice]
    if page_fn is None:
        st.title("Bienvenue 👋")
        st.write("Choisis une section dans la navigation à gauche.")
    else:
        page_fn(db)

if __name__ == "__main__":
    main()
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
