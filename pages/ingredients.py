import streamlit as st
import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session
from db import Ingredient, Supplier
from pages.logic import compute_price_per_base_unit
from units import normalize_unit

def _rerun():
    if hasattr(st, "rerun"):
        st.rerun()
    elif hasattr(st, "experimental_rerun"):
        st.experimental_rerun()

def ingredients_page(db: Session):
    st.header("Ingrédients")

    # Charger les fournisseurs depuis la BD
    suppliers = db.execute(select(Supplier).order_by(Supplier.name)).scalars().all()

    # Création / modification d’un ingrédient
    with st.expander("➕ Ajouter ou modifier un ingrédient", expanded=True):
        name = st.text_input("Nom de l’ingrédient *")
        category = st.text_input("Catégorie", value="Autre")

        col1, col2, col3 = st.columns(3)
        pack_size = col1.number_input("Taille du format", min_value=0.0, value=1000.0, step=10.0)
        pack_unit = col2.selectbox("Unité du format", ["g", "kg", "ml", "l", "unit"], index=0)
        purchase_price = col3.number_input("Prix d’achat ($)", min_value=0.0, value=10.0, step=0.1)

        base_unit = st.selectbox("Unité de base (conversion)", ["g", "ml", "unit"], index=0)
        supplier_choice = st.selectbox(
            "Fournisseur",
            ["(aucun)"] + [s.name for s in suppliers],
        )

        if st.button("💾 Enregistrer l’ingrédient"):
            if not name.strip():
                st.warning("Nom requis.")
            else:
                price_per_base = compute_price_per_base_unit(pack_size, pack_unit, base_unit, purchase_price)
                supplier = next((s for s in suppliers if s.name == supplier_choice), None)
                supplier_id = supplier.id if supplier else None

                existing = db.query(Ingredient).filter(Ingredient.name.ilike(name.strip())).first()
                if existing:
                    existing.category = category.strip() or "Autre"
                    existing.pack_size = pack_size
                    existing.pack_unit = pack_unit
                    existing.purchase_price = purchase_price
                    existing.base_unit = base_unit
                    existing.price_per_base_unit = price_per_base
                    existing.supplier_id = supplier_id
                else:
                    new_ing = Ingredient(
                        name=name.strip(),
                        category=category.strip() or "Autre",
                        pack_size=pack_size,
                        pack_unit=pack_unit,
                        purchase_price=purchase_price,
                        base_unit=base_unit,
                        price_per_base_unit=price_per_base,
                        supplier_id=supplier_id,
                    )
                    db.add(new_ing)

                db.commit()
                st.success("Ingrédient enregistré avec succès ✅")
                st.rerun()

