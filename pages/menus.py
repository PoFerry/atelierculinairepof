import streamlit as st
import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session
from db import Menu, MenuItem, Recipe


def _rerun():
    try:
        st.rerun()
    except AttributeError:
        st.experimental_rerun()


def menus_page(db: Session):
    st.header("Menus")

    # ------------------------------------------------------------------
    # SECTION : Créer / modifier un menu (avec sélection multiple de recettes)
    # ------------------------------------------------------------------
    with st.expander("Créer ou modifier un menu", expanded=True):
        name = st.text_input("Nom du menu *", placeholder="Ex. Menu d'automne")
        notes = st.text_area("Notes (optionnel)", placeholder="Détails logistiques, allergènes, etc.")

        # Multisélection des recettes existantes
        recipes = db.execute(select(Recipe).order_by(Recipe.name)).scalars().all()
        recipe_labels = [r.name for r in recipes]
        selected_recipe_labels = st.multiselect(
            "Recettes à inclure dans ce menu",
            recipe_labels,
            help="Sélectionnez une ou plusieurs recettes déjà enregistrées"
        )

        # Optionnel: définir des 'batches' (= nb de fois que chaque recette sera réalisée)
        default_batches = st.number_input(
            "Quantité par recette (batches) — valeur par défaut",
            min_value=1.0, value=1.0, step=1.0
        )

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
                    # notes : si le modèle Menu n'a pas 'notes', ignore cette ligne
                    if hasattr(menu, "notes"):
                        menu.notes = notes.strip()

                    # Supprimer les anciennes liaisons
                    db.query(MenuItem).filter(MenuItem.menu_id == menu.id).delete()

                    # Recréer les liaisons avec batches par défaut
                    for label in selected_recipe_labels:
                        r = next((x for x in recipes if x.name == label), None)
                        if r:
                            db.add(MenuItem(menu_id=menu.id, recipe_id=r.id, batches=float(default_batches)))

                    db.commit()
                    st.success(f"Menu « {menu.name} » enregistré avec {len(selected_recipe_labels)} recette(s).")
                    _rerun()

                except Exception as e:
                    st.error(f"Erreur lors de l'enregistrement du menu: {e}")

    st.divider()

    # ------------------------------------------------------------------
    # SECTION : Liste des menus existants
    # ------------------------------------------------------------------
    menus = db.query(Menu).order_by(Menu.name).all()
    if not menus:
        st.info("Aucun menu enregistré pour le moment.")
        return

    st.subheader("Menus existants")
    for m in menus:
        st.markdown(f"### 🍽️ {m.name}")
        if hasattr(m, "notes") and m.notes:
            st.caption(m.notes)

        links = db.query(MenuItem).filter(MenuItem.menu_id == m.id).all()
        if not links:
            st.write("_Aucune recette associée._")
        else:
            df = pd.DataFrame(
                [{"Recette": l.recipe.name, "Catégorie": l.recipe.category or "", "Batches": l.batches} for l in links]
            )
            st.dataframe(df, hide_index=True, use_container_width=True)

        col1, col2 = st.columns([1, 1])
        with col1:
            if st.button(f"🗑️ Supprimer le menu « {m.name} »", key=f"del_{m.id}"):
                db.delete(m)
                db.commit()
                st.success(f"Menu « {m.name} » supprimé.")
                _rerun()
