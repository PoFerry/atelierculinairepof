from __future__ import annotations

import streamlit as st
from pathlib import Path
from streamlit_option_menu import option_menu

from db import init_db, SessionLocal

# Import des pages depuis le dossier RENOMMÉ acpof_pages/
from acpof_pages.ingredients import ingredients_page
from acpof_pages.recipes import recipes_page
from acpof_pages.menus import menus_page
from acpof_pages.suppliers import suppliers_page
from acpof_pages.inventory import inventory_page


# ---------- Config globale ----------
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


# ---------- Styles (header + sidebar) ----------
st.markdown(
    """
<style>
/* Top header */
.acpof-topbar {
  background: linear-gradient(90deg,#0f172a,#1e293b);
  color: #e5e7eb;
  padding: 14px 18px;
  border-radius: 12px;
  margin: 8px 0 18px 0;
  display: flex; align-items: center; gap: 12px;
  border: 1px solid rgba(255,255,255,0.06);
}
.acpof-title {
  font-weight: 700; letter-spacing: .3px; font-size: 1.05rem;
}
</style>
""",
    unsafe_allow_html=True,
)


def page_header() -> None:
    """Bandeau commun en haut de chaque page."""
    st.markdown(
        """
        <div class="acpof-topbar">
            <div class="acpof-title">Outils de gestion ACPOF</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def _get_counts(db) -> tuple[int, int, int]:
    """Retours: (nb_ingredients, nb_recettes, nb_menus)."""
    from db import Ingredient, Recipe, Menu
    return (
        db.query(Ingredient).count(),
        db.query(Recipe).count(),
        db.query(Menu).count(),
    )


def sidebar_nav(db) -> str:
    """Affiche le logo + menu d'options dans la sidebar, retourne le nom choisi."""
    with st.sidebar:
        logo = _logo_path()
        if logo:
            st.image(logo, use_column_width=True)
        st.write("")  # petit espace

        ing_n, rec_n, menu_n = _get_counts(db)

        selected = option_menu(
            menu_title=None,
            options=[
                f"Ingrédients ({ing_n})",
                f"Recettes ({rec_n})",
                f"Menus ({menu_n})",
                "Fournisseurs",
                "Inventaire",
            ],
            icons=[
                "basket",      # ingredients
                "book",        # recipes
                "list-task",   # menus
                "truck",       # suppliers
                "box-seam",    # inventory
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


def main() -> None:
    init_db()
    db = SessionLocal()

    # Header commun
    page_header()

    # Navigation latérale (propre, sans doublons)
    selected = sidebar_nav(db)

    # Router
    ROUTES = {
        "Ingrédients": ingredients_page,
        "Recettes": recipes_page,
        "Menus": menus_page,
        "Fournisseurs": suppliers_page,
        "Inventaire": inventory_page,
    }

    # option_menu renvoie "Label (n)"; on retire la partie " (n)"
    base_label = selected.split(" (")[0]

    page_fn = ROUTES.get(base_label)
    if page_fn is None:
        st.error("Page inconnue dans la navigation.")
        return

    # Afficher la page
    page_fn(db)


if __name__ == "__main__":
    main()
