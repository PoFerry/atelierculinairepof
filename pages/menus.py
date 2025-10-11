import streamlit as st
import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session
from db import Menu, MenuRecipe, Recipe


def menus_page(db: Session):
    st.header("Menus")

    # ------------------------------------------------------------------
    # SECTION : Création / modification de menu
    # ------------------------------------------------------------------
    with st.expander("Créer ou modifier un menu", expanded=True):
        name = st.text_input("Nom du menu *", placeholder="Ex. Menu d'automne ou Menu Saint-Valentin")
        notes = st.text_area("Notes (optionnel)", placeholder="Ex. Détails sur le service ou les allergènes...")

        # Sélection des recettes existantes
        recipes = db.execute(select(Recipe).order_by(Recipe.name)).scalars().all()
        recipe_labels = [r.name for r in recipes]
        selected_recipes = st.multiselect(
            "Recettes à inclure dans ce menu",
            recipe_labels,
            help="Sélectionnez une ou plusieurs recettes déjà enregistrées"
        )

        if st.button("Enregistrer le menu"):
            if not name.strip():
                st.warning("Le nom du menu est requis.")
            else:
                try:
                    menu = db.query(Menu).filter(Menu.name.ilike(name.strip())).first()
                    if not menu:
                        menu = Menu(name=name.strip(), notes=notes.strip())
                        db.add(menu)
                        db.commit()
                        db.refresh(menu)
                    else:
                        menu.notes = notes.strip()
                        db.commit()

                    # Supprimer les associations existantes
                    db.query(MenuRecipe).filter(MenuRecipe.menu_id == menu.id).delete()

                    # Ajouter les nouvelles associations
                    for label in selected_recipes:
                        r = next((x for x in recipes if x.name == label), None)
                        if r:
                            db.add(MenuRecipe(menu_id=menu.id, recipe_id=r.id))
                    db.commit()

                    st.success(f"Menu '{menu.name}' enregistré avec {len(selected_recipes)} recette(s).")
                    st.rerun()

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
        if m.notes:
            st.caption(m.notes)

        links = db.query(MenuRecipe).filter(MenuRecipe.menu_id == m.id).all()
        if not links:
            st.write("_Aucune recette associée._")
        else:
            df = pd.DataFrame(
                [{"Recette": l.recipe.name, "Catégorie": l.recipe.category or ""} for l in links]
            )
            st.dataframe(df, hide_index=True, use_container_width=True)

        if st.button(f"🗑️ Supprimer le menu '{m.name}'", key=f"del_{m.id}"):
            db.delete(m)
            db.commit()
            st.success(f"Menu '{m.name}' supprimé.")
            st.rerun()
