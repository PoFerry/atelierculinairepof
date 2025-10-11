import streamlit as st
import pandas as pd
from sqlalchemy.orm import Session
from db import Ingredient, Supplier
from pages.logic import compute_price_per_base_unit
from units import normalize_unit

def ingredients_page(db: Session):
    st.header("Ingrédients")

     with st.expander("➕ Ajouter / Modifier un ingrédient", expanded=True):
        cols = st.columns(3)
        name = cols[0].text_input("Nom *")
        category = cols[1].text_input("Catégorie", value="Autre")
        base_unit = cols[2].selectbox("Unité de base", ["g", "ml", "unit"], index=0)

        # 👇 unités de format compatibles selon l’unité de base
        if base_unit == "g":
            pack_unit_choices = ["mg", "g", "kg"]
            pack_default_idx = 1  # g
        elif base_unit == "ml":
            pack_unit_choices = ["ml", "l"]
            pack_default_idx = 0
        else:  # unit
            pack_unit_choices = ["unit"]
            pack_default_idx = 0

        pack_size = st.number_input("Format d’achat (ex: 1000 g, 1 L…)", min_value=0.0, value=1000.0)
        pack_unit = st.selectbox("Unité du format", pack_unit_choices, index=pack_default_idx)
        purchase_price = st.number_input("Prix d’achat ($)", min_value=0.0, value=10.0, step=0.01)

        suppliers = db.query(Supplier).order_by(Supplier.name).all()
        supplier_names = ["(aucun)"] + [s.name for s in suppliers]
        supplier_sel = st.selectbox("Fournisseur", supplier_names)

        if st.button("Enregistrer"):
            if not name.strip():
                st.error("Nom requis.")
            else:
                try:
                    price_per_base = compute_price_per_base_unit(
                        pack_size=pack_size,
                        pack_unit=pack_unit,
                        base_unit=base_unit,
                        purchase_price=purchase_price,
                    )
                except ValueError as e:
                    st.error(
                        "Vérifie les unités : l’**unité de base** et l’**unité du format** doivent être compatibles. "
                        "Exemples valides : base **g** → format en **mg/g/kg** ; base **ml** → **ml/l** ; base **unit** → **unit**."
                    )
                    st.stop()

                s = None if supplier_sel == "(aucun)" else db.query(Supplier).filter(Supplier.name == supplier_sel).first()

                ing = db.query(Ingredient).filter(Ingredient.name.ilike(name.strip())).first()
                if ing:
                    ing.category = category
                    ing.base_unit = base_unit
                    ing.pack_size = pack_size
                    ing.pack_unit = pack_unit
                    ing.purchase_price = purchase_price
                    ing.price_per_base_unit = price_per_base
                    ing.supplier = s
                else:
                    ing = Ingredient(
                        name=name.strip(),
                        category=category,
                        base_unit=base_unit,
                        pack_size=pack_size,
                        pack_unit=pack_unit,
                        purchase_price=purchase_price,
                        price_per_base_unit=price_per_base,
                        supplier=s,
                    )
                    db.add(ing)
                db.commit()
                st.success(f"Ingrédient enregistré : {ing.name}")


    # --- Liste ---
    rows = db.query(Ingredient).order_by(Ingredient.name).all()
    df = pd.DataFrame([{
        "Nom": i.name,
        "Catégorie": i.category,
        "Unité de base": i.base_unit,
        "Prix par unité de base": round(i.price_per_base_unit, 4),
        "Fournisseur": i.supplier.name if i.supplier else ""
    } for i in rows])
    st.dataframe(df, use_container_width=True)
