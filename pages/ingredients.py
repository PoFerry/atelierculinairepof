import streamlit as st
import pandas as pd
from sqlalchemy.orm import Session
from db import Ingredient, Supplier
from logic import compute_price_per_base_unit
from units import normalize_unit

def ingredients_page(db: Session):
    st.header("Ingrédients")
    with st.expander("➕ Ajouter / Mettre à jour un ingrédient", expanded=True):
        cols = st.columns(4)
        name = cols[0].text_input("Nom *")
        category = cols[1].text_input("Catégorie", value="Autre")
        base_unit = cols[2].selectbox("Unité de base (pour le coût)", ["g", "ml", "unit"], index=0)
        suppliers = db.query(Supplier).order_by(Supplier.name).all()
        supplier_names = ["— Aucun —"] + [s.name for s in suppliers]
        supplier_choice = cols[3].selectbox("Fournisseur (optionnel)", supplier_names, index=0)

        cols2 = st.columns(5)
        pack_size = cols2[0].number_input("Format — quantité *", min_value=0.0, value=1000.0, step=100.0)
        pack_unit = cols2[1].selectbox("Format — unité *", ["mg", "g", "kg", "ml", "l", "unit"], index=2)
        purchase_price = cols2[2].number_input("Prix d'achat pour le format *", min_value=0.0, value=10.0, step=0.5)
        submit = cols2[3].button("Enregistrer")
        create_supplier = cols2[4].button("➕ Créer un fournisseur rapide")

        if create_supplier:
            with st.form("create_supplier_form", clear_on_submit=True):
                st.subheader("Nouveau fournisseur")
                n = st.text_input("Nom du fournisseur *")
                contact = st.text_input("Contact (nom)")
                phone = st.text_input("Téléphone")
                email = st.text_input("Courriel")
                notes = st.text_area("Notes")
                btn = st.form_submit_button("Créer")
                if btn and n.strip():
                    s = Supplier(name=n.strip(), contact=contact, phone=phone, email=email, notes=notes)
                    db.add(s); db.commit(); st.success(f"Fournisseur créé: {s.name}")
                    st.experimental_rerun()

        if submit:
            try:
                ppu = compute_price_per_base_unit(pack_size, pack_unit, base_unit, purchase_price)
                sel_supplier = None
                if supplier_choice != "— Aucun —":
                    sel_supplier = next((s for s in suppliers if s.name == supplier_choice), None)
                existing = db.query(Ingredient).filter(Ingredient.name.ilike(name.strip())).first()
                if existing:
                    existing.category = category.strip() or "Autre"
                    existing.base_unit = base_unit
                    existing.pack_size = float(pack_size)
                    existing.pack_unit = normalize_unit(pack_unit)
                    existing.purchase_price = float(purchase_price)
                    existing.price_per_base_unit = float(ppu)
                    existing.supplier_id = sel_supplier.id if sel_supplier else None
                    db.commit(); st.success(f"Ingrédient mis à jour: {existing.name} ($ {ppu:.4f} / {base_unit})")
                else:
                    ing = Ingredient(name=name.strip(), category=category.strip() or "Autre", base_unit=base_unit,
                                     pack_size=float(pack_size), pack_unit=normalize_unit(pack_unit),
                                     purchase_price=float(purchase_price), price_per_base_unit=float(ppu),
                                     supplier_id=sel_supplier.id if sel_supplier else None)
                    db.add(ing); db.commit(); st.success(f"Ingrédient ajouté: {ing.name} ($ {ppu:.4f} / {base_unit})")
            except Exception as e:
                st.error(f"Erreur: {e}")

    st.divider()
    st.subheader("Catalogue des ingrédients")
    rows = db.query(Ingredient).order_by(Ingredient.category, Ingredient.name).all()
    data = [{
        "Nom": r.name,
        "Catégorie": r.category,
        "Unité de base": r.base_unit,
        "Format": f"{r.pack_size:g} {r.pack_unit}",
        "Prix format ($)": r.purchase_price,
        "Prix/unité de base ($)": round(r.price_per_base_unit, 6),
        "Fournisseur": (r.supplier.name if r.supplier else ""),
    } for r in rows]
    st.dataframe(pd.DataFrame(data), use_container_width=True)

    with st.popover("🗑️ Supprimer un ingrédient"):
        names = [r.name for r in rows]
        sel = st.selectbox("Choisir", names) if names else None
        if sel and st.button("Supprimer définitivement"):
            r = db.query(Ingredient).filter(Ingredient.name == sel).first()
            if r:
                db.delete(r); db.commit(); st.success(f"Supprimé: {sel}")
                st.experimental_rerun()
