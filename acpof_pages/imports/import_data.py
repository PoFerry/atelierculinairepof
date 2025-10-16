"""Outils d'import CSV pour les ingrédients et recettes."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional

import pandas as pd
import streamlit as st
from sqlalchemy import func
from sqlalchemy.orm import Session
import unicodedata
import re

from db import Ingredient, Recipe, RecipeItem, Supplier
from acpof_pages.logic import compute_price_per_base_unit
from units import normalize_unit

try:  # pragma: no cover - dépend d'une config externe
    from sheets_sync import auto_export, import_all_tables, import_table_to_db  # type: ignore
except Exception:  # pragma: no cover - si l'export n'est pas configuré
    def auto_export(*_args, **_kwargs):
        """Fallback silencieux quand sheets_sync n'est pas disponible."""
        pass

    import_all_tables = None
    import_table_to_db = None


# -----------------------------------------------------------------------------
# Résultats d'import
# -----------------------------------------------------------------------------

@dataclass
class ImportResult:
    created: int = 0
    updated: int = 0
    errors: List[str] | None = None

    def as_message(self) -> str:
        errs = self.errors or []
        parts = [
            f"{self.created} créé(s)",
            f"{self.updated} mis à jour",
        ]
        if errs:
            parts.append(f"{len(errs)} erreur(s)")
        return " · ".join(parts)


# -----------------------------------------------------------------------------
# Normalisation des entêtes
# -----------------------------------------------------------------------------

def _canon(s: str) -> str:
    """Normalise une chaîne : retire accents, ponctuation, casse, etc."""
    s = str(s)
    s = unicodedata.normalize("NFKD", s)
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    s = s.lower().strip()
    s = re.sub(r"[’'`]", "", s)          # prix d'achat -> prix dachat
    s = re.sub(r"[_\-.\/]", " ", s)      # unite_base -> unite base
    s = re.sub(r"\s+", " ", s)
    return s


def _normalize_columns(df: pd.DataFrame, aliases: Dict[str, Iterable[str]]) -> pd.DataFrame:
    """Renomme les colonnes d'un DataFrame selon les alias fournis."""
    canon_to_original = {_canon(c): c for c in df.columns}
    rename_map: Dict[str, str] = {}
    for canonical, candidates in aliases.items():
        for candidate in candidates:
            key = _canon(candidate)
            if key in canon_to_original:
                original_col = canon_to_original[key]
                rename_map[original_col] = canonical
                break
    return df.rename(columns=rename_map)


# -----------------------------------------------------------------------------
# Alias de colonnes
# -----------------------------------------------------------------------------

INGREDIENT_ALIASES = {
    "name": {"name", "nom", "nom du produit", "nom du produits", "produit"},
    "category": {"category", "categorie", "catégorie"},
    "base_unit": {
        "base_unit", "unite_base", "unité_base", "unite de base", "unité de base",
        "base", "format de base", "portion", "paquet"
    },
    "pack_size": {
        "pack_size", "format", "taille_colis",
        "format achat", "qté format achat", "qte format achat",
        "qté format d'achat", "qte format d'achat",
        "quantite format achat", "quantité format achat",
        "quantite achat", "quantité achat"
    },
    "pack_unit": {
        "pack_unit", "unite_format", "unité_format", "format_unite",
        "unite format", "unité format",
        "unite achat", "unite d'achat", "unité achat", "unité d'achat",
        "format achat", "caisse", "boite", "boîte", "bte", "sac", "sachet", "paquet",
        "portion", "piece", "pièce"
    },
    "purchase_price": {
        "purchase_price", "prix_achat", "prix", "cout d'achat", "coût d'achat",
        "prix d'achat", "prix dachat"
    },
    "supplier": {"supplier", "fournisseur"},
    "supplier_code": {
        "supplier_code", "code_fournisseur", "code", "code produit chez fournisseur",
        "code produit", "sku fournisseur"
    },
}

RECIPE_ALIASES = {
    "recipe": {"recipe", "recette", "name", "nom"},
    "category": {"category", "categorie", "catégorie"},
    "servings": {"servings", "portions"},
    "instructions": {"instructions", "etapes", "étapes", "steps"},
    "ingredient": {"ingredient", "ingrédient"},
    "quantity": {"quantity", "quantite", "quantité", "qty"},
    "unit": {"unit", "unite", "unité"},
}


# -----------------------------------------------------------------------------
# Coercions & Helpers
# -----------------------------------------------------------------------------

def _coerce_str(value) -> str:
    if pd.isna(value):
        return ""
    return str(value).strip()


def _coerce_float(value) -> Optional[float]:
    """Convertit en float en tolérant :
    - formats FR/EN (1.234,56 / 1,234.56 / 1234,56 / 1234.56)
    - séparateurs de milliers . , espace, NBSP, espace étroit
    - suffixes monnaie (%,$,CAD,EUR,USD) et placeholders (NA, s/o, -, —)
    - valeurs vides -> None
    """
    if pd.isna(value):
        return None
    if isinstance(value, (int, float)):
        return float(value)

    txt = str(value).strip()
    if not txt:
        return None

    # Placeholders à traiter comme vide
    placeholders = {"-", "—", "na", "n/a", "nd", "s/o", "s.o.", "null", "none"}
    if txt.lower() in placeholders:
        return None

    # Supprimer espaces (normaux, NBSP, espace étroit)
    txt = re.sub(r"[\s\u00A0\u202F]+", "", txt)

    # Retirer symboles monétaires et %
    txt = txt.replace("$", "").replace("€", "").replace("£", "")
    txt = re.sub(r"(cad|usd|eur)$", "", txt, flags=re.IGNORECASE)
    txt = txt.replace("%", "")

    # Gestion des séparateurs mixés
    if "," in txt and "." in txt:
        last_comma = txt.rfind(",")
        last_dot = txt.rfind(".")
        if last_comma > last_dot:
            # style EU : '.' milliers, ',' décimal
            txt = txt.replace(".", "")
            txt = txt.replace(",", ".")
        else:
            # style US : ',' milliers, '.' décimal
            txt = txt.replace(",", "")
    else:
        # Un seul séparateur -> virgule = décimal
        if "," in txt and "." not in txt:
            txt = txt.replace(",", ".")

    txt = txt.strip()
    if txt == "" or txt in {".", "-.", "+."}:
        return None

    try:
        return float(txt)
    except ValueError:
        txt2 = re.sub(r"[^0-9\.\-+]", "", txt)
        if txt2 in ("", ".", "-.", "+."):
            return None
        try:
            return float(txt2)
        except Exception:
            raise ValueError(f"Valeur numérique invalide: {value}")


# -----------------------------------------------------------------------------
# Unités : nettoyage + familles
# -----------------------------------------------------------------------------

_UNIT_COUNT = {
    "unit", "unite", "u", "piece", "pièce", "pc", "pz",
    "portion", "paquet", "caisse", "boite", "boîte", "bte", "sac", "sachet"
}
_UNIT_MASS  = {"g", "kg", "lb"}
_UNIT_VOL   = {"ml", "l"}

def _clean_unit_text(s: str) -> str:
    """Nettoie les unités saisies librement avant normalize_unit."""
    s = str(s or "").strip().lower()
    s = unicodedata.normalize("NFKD", s)
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    s = s.replace("’", "").replace("'", "").replace("`", "")
    # Enlever préfixes / ponctuations (ex: "/g", "- kg")
    s = re.sub(r"^[\/\-\–\—\s]+", "", s)
    s = re.sub(r"\s+", " ", s).strip()
    # Synonymes usuels -> formes de base
    synonyms = {
        "unite": "unit", "u": "unit", "piece": "unit", "pc": "unit", "pz": "unit",
        "portion": "unit", "paquet": "unit", "caisse": "unit",
        "boite": "unit", "boîte": "unit", "bte": "unit",
        "sac": "unit", "sachet": "unit",
        "litre": "l", "liter": "l", "millilitre": "ml", "milliliter": "ml",
        "gramme": "g", "kilogramme": "kg", "lbs": "lb"
    }
    return synonyms.get(s, s)

def _unit_family(u: str) -> Optional[str]:
    if not u:
        return None
    if u in _UNIT_COUNT:
        return "count"
    if u in _UNIT_MASS:
        return "mass"
    if u in _UNIT_VOL:
        return "vol"
    return None

def _canon_base_unit(u: str) -> str:
    """Force base_unit dans {g, ml, unit}."""
    fam = _unit_family(u)
    if fam == "mass":
        return "g"   # kg/lb seront convertis vers g pour la base
    if fam == "vol":
        return "ml"  # l -> ml pour la base
    if fam == "count":
        return "unit"
    return ""


def _reconcile_units(base_u: str, pack_u: str, pack_size: Optional[float]) -> tuple[str, str]:
    """
    Harmonise base_unit et pack_unit :
    - base_unit forcée dans {g, ml, unit} quand c'est possible
    - si base manquante : on déduit depuis pack_unit ; sinon fallback 'unit'
    - si pack='unit' & base mass/vol -> pack = base (pack_size exprimé dans la base)
    - si base=count & pack mass/vol -> base = canon(pack)
    - si base mass & pack vol (ou inverse) -> base s'aligne sur pack
    """
    base_u = _clean_unit_text(base_u)
    pack_u = _clean_unit_text(pack_u)

    def fam(u: str) -> Optional[str]:
        return _unit_family(u)

    def canon_base(u: str) -> str:
        return _canon_base_unit(u)

    base_u_c = canon_base(base_u)
    pack_f = fam(pack_u)
    base_f = fam(base_u_c)

    # Base manquante -> tenter depuis pack ; sinon 'unit'
    if not base_u_c:
        if pack_f:
            base_u_c = canon_base(pack_u)
            base_f = fam(base_u_c)
        else:
            base_u_c = "unit"
            base_f = "count"

    # pack unit vide -> pack = base
    if not pack_u:
        pack_u = base_u_c
        pack_f = base_f

    # pack=count & base mass/vol -> pack = base
    if pack_f == "count" and base_f in {"mass", "vol"}:
        pack_u = base_u_c
        pack_f = base_f

    # base=count & pack mass/vol -> base = pack
    if base_f == "count" and pack_f in {"mass", "vol"}:
        base_u_c = canon_base(pack_u)
        base_f = fam(base_u_c)

    # base mass & pack vol (ou inverse) -> aligner base sur pack
    if base_f in {"mass", "vol"} and pack_f in {"mass", "vol"} and base_f != pack_f:
        base_u_c = canon_base(pack_u)
        base_f = fam(base_u_c)

    # Normalisation finale via normalize_unit
    norm_base = normalize_unit(base_u_c) if base_u_c else "unit"
    norm_pack = normalize_unit(pack_u) if pack_u else norm_base
    return norm_base, norm_pack


# -----------------------------------------------------------------------------
# Résolution fournisseur
# -----------------------------------------------------------------------------

def _resolve_supplier(db: Session, cache: Dict[str, Supplier], name: str) -> Supplier | None:
    if not name:
        return None
    key = name.strip().lower()
    if key in cache:
        return cache[key]
    supplier = (
        db.query(Supplier)
        .filter(func.lower(Supplier.name) == key)
        .one_or_none()
    )
    if not supplier:
        supplier = Supplier(name=name.strip())
        db.add(supplier)
        db.flush()
    cache[key] = supplier
    return supplier


# -----------------------------------------------------------------------------
# Parsing ingrédients (tolérant aux cases vides)
# -----------------------------------------------------------------------------

def _parse_ingredient_rows(df: pd.DataFrame) -> tuple[List[dict], List[str]]:
    entries: List[dict] = []
    skipped: List[str] = []
    errors: List[str] = []

    df = _normalize_columns(df, INGREDIENT_ALIASES)
    required = {"name", "base_unit", "pack_size", "pack_unit", "purchase_price"}
    missing = [col for col in required if col not in df.columns]
    if missing:
        errors.append(
            "Colonnes manquantes pour les ingrédients: " + ", ".join(sorted(missing))
        )
        return ([], errors)

    for idx, row in df.iterrows():
        line_no = idx + 2  # entête = ligne 1
        try:
            name = _coerce_str(row.get("name"))
            if not name:
                skipped.append(f"Ligne {line_no}: nom vide → ignorée")
                continue

            # Tolérance : si vide, on met des valeurs par défaut raisonnables
            pack_size = _coerce_float(row.get("pack_size")) or 1.0
            purchase_price = _coerce_float(row.get("purchase_price")) or 0.0

            base_u_txt = _coerce_str(row.get("base_unit"))
            pack_u_txt = _coerce_str(row.get("pack_unit"))

            # Déduction/harmonisation des unités (même si vides)
            base_unit, pack_unit = _reconcile_units(base_u_txt, pack_u_txt, pack_size)
            if not base_unit:
                base_unit = "unit"
            if not pack_unit:
                pack_unit = base_unit

            # Calcul du coût par unité (si échec, on met 0.0)
            try:
                price_per_base = compute_price_per_base_unit(
                    pack_size=pack_size,
                    pack_unit=pack_unit,
                    base_unit=base_unit,
                    purchase_price=purchase_price,
                )
            except Exception:
                price_per_base = 0.0

            entries.append(
                {
                    "name": name,
                    "category": _coerce_str(row.get("category")) or "Autre",
                    "base_unit": base_unit,
                    "pack_size": float(pack_size),
                    "pack_unit": pack_unit,
                    "purchase_price": float(purchase_price),
                    "price_per_base_unit": float(price_per_base),
                    "supplier": _coerce_str(row.get("supplier")),
                    "supplier_code": _coerce_str(row.get("supplier_code")),
                }
            )

        except Exception as exc:
            errors.append(f"Ligne {line_no}: {exc}")

    if skipped:
        errors.append(f"{len(skipped)} ligne(s) ignorée(s) car incomplètes :\n" + "\n".join(skipped[:10]))
    return entries, errors


def _apply_ingredient_import(db: Session, rows: List[dict]) -> ImportResult:
    created = 0
    updated = 0
    supplier_cache: Dict[str, Supplier] = {}

    for payload in rows:
        supplier = _resolve_supplier(db, supplier_cache, payload["supplier"])
        ingredient = (
            db.query(Ingredient)
            .filter(func.lower(Ingredient.name) == payload["name"].lower())
            .one_or_none()
        )
        if ingredient:
            updated += 1
        else:
            ingredient = Ingredient(name=payload["name"])
            db.add(ingredient)
            created += 1

        ingredient.category = payload["category"] or "Autre"
        ingredient.base_unit = payload["base_unit"]
        ingredient.pack_size = payload["pack_size"]
        ingredient.pack_unit = payload["pack_unit"]
        ingredient.purchase_price = payload["purchase_price"]
        ingredient.price_per_base_unit = payload["price_per_base_unit"]
        ingredient.supplier_id = supplier.id if supplier else None
        ingredient.supplier_code = payload["supplier_code"] or ""

    db.commit()
    auto_export(db, "ingredients")
    return ImportResult(created=created, updated=updated, errors=[])


# -----------------------------------------------------------------------------
# Parsing recettes
# -----------------------------------------------------------------------------

def _parse_recipe_rows(df: pd.DataFrame, db: Session) -> tuple[Dict[str, dict], List[str]]:
    df = _normalize_columns(df, RECIPE_ALIASES)
    required = {"recipe", "ingredient", "quantity"}
    missing = [col for col in required if col not in df.columns]
    errors: List[str] = []
    if missing:
        errors.append(
            "Colonnes manquantes pour les recettes: " + ", ".join(sorted(missing))
        )
        return ({}, errors)

    recipes: Dict[str, dict] = {}
    for idx, row in df.iterrows():
        line_no = idx + 2
        name = _coerce_str(row.get("recipe"))
        if not name:
            errors.append(f"Ligne {line_no}: nom de recette manquant")
            continue
        rec = recipes.setdefault(
            name,
            {"category": "", "servings": 1, "instructions": "", "items": []},
        )
        if row.get("category") and not rec["category"]:
            rec["category"] = _coerce_str(row.get("category"))
        servings = row.get("servings")
        if servings and rec["servings"] == 1:
            try:
                rec["servings"] = max(1, int(float(servings)))
            except Exception:
                errors.append(f"Ligne {line_no}: portions invalides")
        instr = _coerce_str(row.get("instructions"))
        if instr:
            if rec["instructions"]:
                rec["instructions"] += "\n" + instr
            else:
                rec["instructions"] = instr

        ing_name = _coerce_str(row.get("ingredient"))
        if not ing_name:
            continue
        qty_val = row.get("quantity")
        try:
            qty = _coerce_float(qty_val)
        except ValueError as exc:
            errors.append(f"Ligne {line_no}: {exc}")
            continue
        if qty is None:
            errors.append(f"Ligne {line_no}: quantité manquante")
            continue
        unit = _clean_unit_text(_coerce_str(row.get("unit")) or "g")
        unit = normalize_unit(unit)
        ingredient = (
            db.query(Ingredient)
            .filter(func.lower(Ingredient.name) == ing_name.lower())
            .one_or_none()
        )
        if not ingredient:
            errors.append(
                f"Ligne {line_no}: ingrédient inconnu '{ing_name}' (créez-le avant import)"
            )
            continue
        rec["items"].append({
            "ingredient": ingredient,
            "quantity": float(qty),
            "unit": unit,
        })

    for name, rec in list(recipes.items()):
        if not rec["items"]:
            errors.append(
                f"Recette '{name}' ignorée car aucun ingrédient valide n'a été fourni"
            )
            recipes.pop(name, None)

    return recipes, errors


def _apply_recipe_import(db: Session, recipes: Dict[str, dict]) -> ImportResult:
    created = 0
    updated = 0
    for name, payload in recipes.items():
        recipe = (
            db.query(Recipe)
            .filter(func.lower(Recipe.name) == name.lower())
            .one_or_none()
        )
        if recipe:
            updated += 1
        else:
            recipe = Recipe(name=name)
            db.add(recipe)
            db.flush()
            created += 1

        recipe.category = payload.get("category", "") or ""
        recipe.servings = payload.get("servings", 1) or 1
        recipe.instructions = payload.get("instructions", "") or ""
        recipe.items[:] = []
        for item in payload["items"]:
            recipe.items.append(
                RecipeItem(
                    ingredient_id=item["ingredient"].id,
                    quantity=item["quantity"],
                    unit=item["unit"],
                )
            )

    db.commit()
    auto_export(db, "recipes")
    auto_export(db, "recipe_items")
    return ImportResult(created=created, updated=updated, errors=[])


# -----------------------------------------------------------------------------
# Lecture CSV tolérante
# -----------------------------------------------------------------------------

def _read_uploaded_csv(uploaded_file) -> pd.DataFrame:
    if uploaded_file is None:
        raise ValueError("Aucun fichier fourni")
    try:
        uploaded_file.seek(0)
    except Exception:
        pass
    try:
        # sep=None -> auto-détection (virgule/point-virgule/tab)
        return pd.read_csv(uploaded_file, sep=None, engine="python", encoding="utf-8-sig")
    except UnicodeDecodeError:
        uploaded_file.seek(0)
        return pd.read_csv(uploaded_file, sep=None, engine="python", encoding="latin-1")


# -----------------------------------------------------------------------------
# UI Streamlit
# -----------------------------------------------------------------------------

def _render_sheet_import_section(db: Session) -> None:
    if import_table_to_db is None or import_all_tables is None:
        st.info(
            "Synchronisation Google Sheets non configurée. "
            "Ajoutez vos secrets Streamlit pour activer cette fonctionnalité."
        )
        return

    st.subheader("Importer depuis Google Sheets")
    st.write(
        "Utilisez cette section pour rapatrier les données depuis la feuille de calcul "
        "connectée (remplacement complet des tables)."
    )
    col_all, col_select = st.columns(2)
    with col_all:
        if st.button("Importer toutes les tables", use_container_width=True):
            with st.spinner("Import des tables depuis Google Sheets…"):
                try:
                    res = import_all_tables(db)
                except Exception as exc:
                    st.error(f"Import global échoué : {exc}")
                else:
                    st.success(
                        "Import terminé : "
                        + ", ".join(f"{tbl}: {count}" for tbl, count in res.items())
                    )
    with col_select:
        table = st.selectbox("Table à importer", options=[
            "suppliers",
            "ingredients",
            "recipes",
            "recipe_items",
            "menus",
            "menu_items",
            "stock_movements",
        ])
        if st.button("Importer la table sélectionnée", use_container_width=True):
            with st.spinner(f"Import de {table}…"):
                try:
                    count = import_table_to_db(db, table)
                except Exception as exc:
                    st.error(f"Import échoué : {exc}")
                else:
                    st.success(f"{count} ligne(s) importée(s) depuis Google Sheets.")


def _render_csv_import_section(db: Session) -> None:
    st.subheader("Importer depuis un CSV")
    st.markdown(
        "Préparez un fichier CSV (séparateur virgule ou point-virgule) avec les colonnes "
        "suivantes :"
    )
    st.markdown(
        "- **Ingrédients** : `name`, `category`, `base_unit`, `pack_size`, `pack_unit`, `purchase_price`, `supplier`, `supplier_code`\n"
        "- **Recettes** : `recipe`, `category`, `servings`, `instructions`, `ingredient`, `quantity`, `unit`"
    )

    st.markdown("---")
    st.markdown("### Ingrédients")
    ing_file = st.file_uploader(
        "Fichier CSV des ingrédients",
        type=["csv"],
        key="ing_csv_uploader",
    )
    if st.button("Importer les ingrédients", disabled=ing_file is None):
        try:
            df = _read_uploaded_csv(ing_file)
            rows, parse_errors = _parse_ingredient_rows(df)
            if parse_errors:
                st.error("\n".join(parse_errors))
            if rows:
                with st.spinner("Import des ingrédients…"):
                    res = _apply_ingredient_import(db, rows)
                st.success(f"Import ingrédients terminé : {res.as_message()}")
        except Exception as exc:
            db.rollback()
            st.error(f"Import ingrédients échoué : {exc}")

    st.markdown("---")
    st.markdown("### Recettes")
    recipe_file = st.file_uploader(
        "Fichier CSV des recettes",
        type=["csv"],
        key="recipe_csv_uploader",
    )
    if st.button("Importer les recettes", disabled=recipe_file is None):
        try:
            df = _read_uploaded_csv(recipe_file)
            recipes, parse_errors = _parse_recipe_rows(df, db)
            if parse_errors:
                st.error("\n".join(parse_errors))
            if recipes:
                with st.spinner("Import des recettes…"):
                    res = _apply_recipe_import(db, recipes)
                st.success(f"Import recettes terminé : {res.as_message()}")
        except Exception as exc:
            db.rollback()
            st.error(f"Import recettes échoué : {exc}")


def imports_page(db: Session) -> None:
    st.header("Importations")
    st.write(
        "Chargez vos données depuis des fichiers CSV ou depuis Google Sheets pour "
        "mettre à jour rapidement vos ingrédients et recettes. Les importations "
        "remplacent/actualisent les éléments existants sur la base du nom."
    )

    tabs = st.tabs(["CSV", "Google Sheets"])
    with tabs[0]:
        _render_csv_import_section(db)
    with tabs[1]:
        _render_sheet_import_section(db)
