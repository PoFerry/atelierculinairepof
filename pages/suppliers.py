import streamlit as st
import pandas as pd
from sqlalchemy.orm import Session
from db import Supplier

def suppliers_page(db: Session):
    st.header("Fournisseurs")

    # --- Ajouter ou mettre à jour un fournisseur ---
    with st.expander("➕ Ajouter / Mettre à jour un fournisseur", expanded=True):
        cols = st.columns(3)
        name = cols[0].text_input("Nom *")
        contact = cols[1].text_input("Contact")
        phone = cols[2].text_input("Téléphone")
        email = st.text_input("Courriel")
        notes = st.text_area("Notes")

        if st.button("Enregistrer"):
            if not name.strip():
                st.error("Nom requis")
            else:
                existing = db.query(Supplier).filter(Supplier.name.ilike(name.strip())).first()
                if existing:
                    existing.contact = contact
                    existing.phone = phone
                    existing.email = email
                    existing.notes = notes
                    db.commit()
                    st.success(f"Fournisseur mis à jour: {existing.name}")
                else:
                    s = Supplier(name=name.strip(), contact=contact, phone=phone, email=email, notes=notes)
                    db.add(s)
                    db.commit()
                    st.success(f"Fournisseur créé: {s.name}")

    # --- Liste des fournisseurs ---
    st.divider()
    rows = db.query(Supplier).order_by(Supplier.name).all()
    df = pd.DataFrame([{
        "Nom": s.name,
        "Contact": s.contact,
        "Téléphone": s.phone,
        "Courriel": s.email,
        "Notes": s.notes
    } for s in rows])
    st.dataframe(df, use_container_width=True)

    # --- Suppression ---
    with st.popover("🗑️ Supprimer un fournisseur"):
        names = [s.name for s in rows]
        sel = st.selectbox("Choisir", names) if names else None
        if sel and st.button("Supprimer définitivement"):
            s = db.query(Supplier).filter(Supplier.name == sel).first()
            if s:
                db.delete(s)
                db.commit()
                st.success(f"Supprimé: {sel}")
                st.experimental_rerun()
