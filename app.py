from __future__ import annotations

import streamlit as st
from pathlib import Path
from streamlit_option_menu import option_menu
from importlib import import_module

from sqlalchemy import func, select
from sqlalchemy.exc import OperationalError

from db import init_db, SessionLocal

# ---------- Config ----------
st.set_page_config(
    page_title="Atelier Culinaire POF",
    page_icon="🍽️",
    layout="wide",
    initial_sidebar_state="expanded",
)

APP_DIR = Path(__file__).parent
LOGO_CANDIDATES = [
    APP_DIR / "Logo_atelierPOF.png",
    APP_DIR / "logo_atelierpof.png",
    APP_DIR / "assets" / "Logo_atelierPOF.png",
]

def _logo_path() -> str | None:
    for p in LOGO_CANDIDATES:
        if p.exists():
            return str(p)
    return None

# ---------- Styles (header) ----------
st.markdown(
    """
<style>
.acpof-topbar {
  background: linear-gradient(90deg,#0f172a,#1e293b);
  color: #e5e7eb;
  padding: 14px 18px;
  border-radius: 12px;
  margin: 8px 0 18px 0;
  display: flex; align-items: center; gap: 12px;
  border: 1px solid rgba(255,255,255,0.06);
}
.acpof-title { font-weight: 700; letter-spacing: .3px; font-size: 1.05rem; }
</style>
""",
    unsafe_allow_html=True,
)

def page_header() -> None:
    st.markdown(
        """
        <div class="acpof-topbar">
            <div class="acpof-title">Outils de gestion ACPOF</div>
        </div>
        """,
        unsafe_allow_html=True,
    )

def _get_counts(db) -> tuple[int, int, int]:
    from db import Ingredient, Menu, Recipe

    def _count(model):
        stmt = select(func.count()).select_from(model)
        return db.execute(stmt).scalar_one()

    for attempt in range(2):
        try:
            return tuple(_count(model) for model in (Ingredient, Recipe, Menu))
        except OperationalError:
            db.rollback()
            if attempt == 0:
                # Ensure the schema exists before retrying (e.g. fresh database).
                init_db()
                continue
            st.warning(
                "Impossible de récupérer les compteurs depuis la base de données. "
                "Vérifiez la connexion puis réessayez."
            )
            break

    return (0, 0, 0)


def sidebar_nav(db) -> str:
    with st.sidebar:
        logo = _logo_path()
        if logo:
            st.image(logo, use_column_width=True)
        st.write("")
        ing_n, rec_n, menu_n = _get_counts(db)
        selected = option_menu(
            menu_title=None,
            options=[
                f"Ingrédients ({ing_n})",
                f"Recettes ({rec_n})",
                f"Menus ({menu_n})",
                "Fournisseurs",
                "Inventaire",
                   "Importations",
            ],
            icons=[
                "basket",
                "book",
                "list-task",
                "truck",
                "box-seam",
                "cloud-arrow-up",
            ],
            default_index=0,
            styles={
                "container": {"background-color": "#0f172a", "padding": "0.5rem 0.25rem"},
                "icon": {"color": "#cbd5e1", "font-size": "16px"},
                "nav-link": {
                    "color": "#e5e7eb",
                    "font-size": "15px",
                    "text-align": "left",
                    "margin": "4px 6px",
                    "padding": "10px 12px",
                    "border-radius": "10px",
                },
                "nav-link-selected": {"background-color": "#1e293b"},
            },
        )
        st.markdown("---")
        st.caption("Atelier Culinaire Pierre-Olivier Ferry")
        return selected

# ---------- Import paresseux ----------
ROUTES = {
    "Ingrédients": ("acpof_pages.ingredients", "ingredients_page"),
    "Recettes": ("acpof_pages.recipes", "recipes_page"),
    "Menus": ("acpof_pages.menus", "menus_page"),
    "Fournisseurs": ("acpof_pages.suppliers", "suppliers_page"),
    "Inventaire": ("acpof_pages.inventory", "inventory_page"),
    "Importations": ("acpof_pages.imports.import_data", "imports_page"),
}

def load_page_callable(label: str):
    mod_name, fn_name = ROUTES[label]
    try:
        mod = import_module(mod_name)
        return getattr(mod, fn_name)
    except Exception as e:
        st.error(f"Erreur lors du chargement de la page **{label}** ({mod_name}.{fn_name}) : {e}")
        st.stop()

def main() -> None:
    init_db()
    db = SessionLocal()

    try:
        page_header()
        selected = sidebar_nav(db)

        base_label = selected.split(" (")[0]
        if base_label not in ROUTES:
            st.error("Page inconnue dans la navigation.")
            return

        page_fn = load_page_callable(base_label)
        page_fn(db)
    finally:
        db.close()

if __name__ == "__main__":
    main()
    
