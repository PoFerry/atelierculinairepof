# Atelier Culinaire POF — App 2.0 (Version améliorée)

Application Streamlit + SQLAlchemy + SQLite pour gérer ingrédients, recettes et menus,
avec **préparation** pour fournisseurs, inventaire et exports.

## ✅ Inclus
- Ingrédients: format d'achat, prix d'achat, **prix/unité de base**, catégorie, **fournisseur (optionnel)**.
- Recettes: items avec unités (mg/g/kg/ml/L/unit), **coût total** et **par portion**.
- Menus: sélection de recettes + batches, **liste d'achats agrégée**.
- Exports: utilitaire `export_utils.py` pour exporter en CSV les vues (ex. liste d'achats).
- Schéma prêt pour l'**inventaire**: tables `suppliers`, `stock_movements` (non utilisées dans l'UI, mais présentes).

## ▶️ Démarrer
```bash
python -m venv .venv && source .venv/bin/activate     # Windows: .venv\Scripts\activate
pip install -r requirements.txt
streamlit run app.py
```
