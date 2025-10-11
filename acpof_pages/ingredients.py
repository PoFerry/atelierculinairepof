import streamlit as st
import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session
from db import Ingredient, Supplier
from pages.logic import compute_price_per_base_unit
from units import normalize_unit


def _rerun():
    try:
        st.rerun()
    except AttributeError:
        # Compatibilité avec anciennes versions de Streamlit
        st.experimental_rerun()


def ingredients_page(db: Session) -> None:
    st.header("Ingrédients")

    # ---- Charger fournisseurs et préparer un mapping nom -> id ----
    sup_rows = db.execute(select(Supplier.id, Supplier.name).order_by(Supplier.name)).all()
    # sup_rows est une liste de tuples (id, name)
    name_to_id = {name: sup_id for (sup_id, name) in sup_rows}
    supplier_options = ["(aucun)"] + list(name_to_id.keys())

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

        supplier_sel = st.selectbox("Fournisseur", supplier_options, index=0)

        if st.button("Enregistrer"):
            if not name.strip():
                st.error("Nom requis.")
            else:
                try:
                    # 1) calcul prix/unité de base
                    price_per_base = compute_price_per_base_unit(
                        pack_size=pack_size,
                        pack_unit=pack_unit,
                        base_unit=base_unit,
                        purchase_price=purchase_price,
                    )

                    # 2) supplier_id (None si (aucun))
                    supplier_id = None if supplier_sel == "(aucun)" else name_to_id.get(supplier_sel)

                    # 3) upsert ingrédient
                    ing = (
                        db.query(Ingredient)
                        .filter(Ingredient.name.ilike(name.strip()))
                        .first()
                    )
                    if ing:
                        ing.category = (category or "Autre").strip()
                        ing.base_unit = base_unit
                        ing.pack_size = float(pack_size or 0)
                        ing.pack_unit = normalize_unit(pack_unit)
                        ing.purchase_price = float(purchase_price or 0)
                        ing.price_per_base_unit = float(price_per_base)
                        ing.supplier_id = supplier_id
                    else:
                        ing = Ingredient(
                            name=name.strip(),
                            category=(category or "Autre").strip(),
                            base_unit=base_unit,
                            pack_size=float(pack_size or 0),
                            pack_unit=normalize_unit(pack_unit),
                            purchase_price=float(purchase_price or 0),
                            price_per_base_unit=float(price_per_base),
                            supplier_id=supplier_id,
                        )
                        db.add(ing)

                    db.commit()
                    st.success(f"Ingrédient enregistré : {ing.name}")
                    _rerun()

                except ValueError:
                    st.error(
                        "Vérifie les unités : base et format doivent être compatibles.\n"
                        "base g → mg/g/kg ; base ml → ml/l ; base unit → unit."
                    )
                except Exception as e:
                    st.error(f"Erreur inattendue: {e}")

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
