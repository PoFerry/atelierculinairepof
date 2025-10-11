import streamlit as st
import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session
from db import Ingredient, Supplier
from pages.logic import compute_price_per_base_unit
from units import normalize_unit


def _rerun():
    # Compatibilité selon version Streamlit
    if hasattr(st, "rerun"):
        st.rerun()
    elif hasattr(st, "experimental_rerun"):
        st.experimental_rerun()


def ingredients_page(db: Session) -> None:
    st.header("Ingrédients")

    # ---- Charger fournisseurs ----
    suppliers = db.execute(select(Supplier).order_by(Supplier.name)).scalars().all()

    # ---- Formulaire Ajouter / Modifier ----
    with st.expander("➕ Ajouter / Modifier un ingrédient", expanded=True):
        cols = st.columns(3)
        name = cols[0].text_input("Nom *")
        category = cols[1].text_input("Catégorie", value="Autre")
        base_unit = cols[2].selectbox("Unité de base", ["g", "ml", "unit"], index=0)

        # Unités de format compatibles selon l’unité de base
        if base_unit == "g":
            pack_unit_choices = ["mg", "g", "kg"]
            pack_default_idx = 1
        elif base_unit == "ml":
            pack_unit_choices = ["ml", "l"]
            pack_default_idx = 0
        else:
            pack_unit_choices = ["unit"]
            pack_default_idx = 0

        pack_size = st.number_input("Format d’achat (ex: 1000 g, 1 L…)", min_value=0.0, value=1000.0)
        pack_unit = st.selectbox("Unité du format", pack_unit_choices, index=pack_default_idx)
        purchase_price = st.number_input("Prix d’achat ($)", min_value=0.0, value=10.0, step=0.01)

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
                except ValueError:
                    st.error(
                        "Vérifie les unités : base et format doivent être compatibles.\n"
                        "base g → mg/g/kg ; base ml → ml/l ; base unit → unit."
                    )
                    return

                supplier = None if supplier_sel == "(aucun)" else next((s for s in suppliers if s.name == supplier_sel), None)

                ing = db.query(Ingredient).filter(Ingredient.name.ilike(name.strip())).first()
                if ing:
                    ing.category = category.strip() or "Autre"
                    ing.base_unit = base_unit
                    ing.pack_size = pack_size
                    ing.pack_unit = pack_unit
                    ing.purchase_price = purchase_price
                    ing.price_per_base_unit = price_per_base
                    ing.supplier = supplier
                else:
                    ing = Ingredient(
                        name=name.strip(),
                        category=category.strip() or "Autre",
                        base_unit=base_unit,
                        pack_size=pack_size,
                        pack_unit=pack_unit,
                        purchase_price=purchase_price,
                        price_per_base_unit=price_per_base,
                        supplier=supplier,
                    )
                    db.add(ing)

                db.commit()
                st.success(f"Ingrédient enregistré : {ing.name}")
                _rerun()

    # ---- Liste des ingrédients ----
    rows = db.query(Ingredient).order_by(Ingredient.name).all()
    df = pd.DataFrame([{
        "Nom": i.name,
        "Catégorie": i.category,
        "Unité de base": i.base_unit,
        "Format achat": f"{i.pack_size:g} {i.pack_unit}",
        "Prix d’achat ($)": round(i.purchase_price, 2),
        "Prix par unité de base": round(i.price_per_base_unit, 4),
        "Fournisseur": (i.supplier.name if i.supplier else "")
    } for i in rows])

    if not df.empty:
        st.dataframe(
            df.style.format({
                "Prix d’achat ($)": "{:.2f}",
                "Prix par unité de base": "{:.4f}",
            }),
            use_container_width=True
        )
    else:
        st.info("Aucun ingrédient saisi pour l’instant.")

    # ---- Suppression ----
    with st.popover("🗑️ Supprimer un ingrédient"):
        if rows:
            sel = st.selectbox("Choisir un ingrédient", [i.name for i in rows])
            if st.button("Supprimer définitivement"):
                target = db.query(Ingredient).filter(Ingredient.name == sel).first()
                if target:
                    db.delete(target)
                    db.commit()
                    st.success(f"Supprimé : {sel}")
                    _rerun()
