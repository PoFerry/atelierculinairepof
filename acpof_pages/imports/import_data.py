# acpof_pages/imports/import_data.py
"""Outils d'import CSV pour les ingrédients et recettes (robuste et tolérant)."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional, Tuple

import pandas as pd
import streamlit as st
from sqlalchemy import func
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError

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


# ------------------------- Modèle de résultat -------------------------

@dataclass
class ImportResult:
    created: int = 0
    updated: int = 0
    errors: List[str] | None = None
    ignored: int = 0

    def as_message(self) -> str:
        errs = self.errors or []
        parts = [
            f"{self.created} créé(s)",
            f"{self.updated} mis à jour",
        ]
        if self.ignored:
            parts.append(f"{self.ignored} ignoré(s)")
        if errs:
            parts.append(f"{len(errs)} erreur(s)")
        return " · ".join(parts)


# ------------------------- Aliases colonnes -------------------------

# Alias de colonnes acceptés (en minuscules déjà normalisés)
INGREDIENT_ALIASES = {
    "name": {"name", "nom", "produit", "nom du produit", "nom du produits", "nom de l'ingredient", "nom de l ingredient"},
    "category": {"category", "categorie", "catégorie", "famille", "groupe", "categorie du produit"},
    "base_unit": {"base_unit", "unite_base", "unité_base", "base", "format de base", "format unitaire", "unite unitaire"},
    "pack_size": {
        "pack_size", "format", "taille_colis",
        "quantite format achat", "quantité format achat", "quantite d'unite dans format d'achat",
        "quantite d unite dans format d achat", "quantite achat", "quantité achat", "qte format achat", "qte format dachat",
        "poids format", "volume format"
    },
    "pack_unit": {
        "pack_unit", "unite_format", "unité_format", "format_unite",
        "unite du format d'achat", "unite du format d achat", "unite d'achat", "unité d'achat",
        "format achat"
    },
    "purchase_price": {
        "purchase_price", "prix_achat", "prix", "prix du format d'achat en dollar",
        "cout d'achat", "coût d'achat", "prix d'achat", "coût", "cost"
    },
    "supplier": {"supplier", "fournisseur", "nom du producteur ou fournisseur"},
    "supplier_code": {"supplier_code", "code_fournisseur", "code", "code produit chez fournisseur", "code produit", "sku fournisseur"},
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


# ------------------------- Utilitaires parsing -------------------------

def _normalize_columns(df: pd.DataFrame, aliases: Dict[str, Iterable[str]]) -> pd.DataFrame:
    # normalise les noms de colonnes pour matcher nos alias
    columns = {c: str(c).strip().lower() for c in df.columns}
    df = df.rename(columns=columns)
    rename_map: Dict[str, str] = {}
    for canonical, candidates in aliases.items():
        for candidate in candidates:
            if candidate in df.columns:
                rename_map[candidate] = canonical
                break
    return df.rename(columns=rename_map)


def _coerce_str(value) -> str:
    if pd.isna(value):
        return ""
    return str(value).strip()


def _coerce_float(value) -> Optional[float]:
    """Tolérant FR/EN : espaces, milliers, virgules, monnaie, %, placeholders."""
    if pd.isna(value):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    txt = str(value).strip()
    if not txt:
        return None
    # placeholders qui signifient "vide"
    if txt.lower() in {"na", "n/a", "nd", "s/o", "null", "none", "-", "—"}:
        return None
    # remove spaces (incl. insécables) et symboles monétaires/monnaies
    txt = (
        txt.replace("\u00A0", "")
           .replace("\u202F", "")
           .replace(" ", "")
           .replace("$", "")
           .replace("€", "")
           .replace("£", "")
    )
    for suffix in ("cad", "usd", "eur", "%"):
        if txt.lower().endswith(suffix):
            txt = txt[: -len(suffix)]
    # gérer virgule et point
    if "," in txt and "." in txt:
        # si la virgule est la décimale (à droite du point), on enlève le séparateur de milliers
        if txt.rfind(",") > txt.rfind("."):
            txt = txt.replace(".", "").replace(",", ".")
        else:
            txt = txt.replace(",", "")
    elif "," in txt:
        txt = txt.replace(",", ".")
    try:
        return float(txt)
    except ValueError:
        # ultime tentative : ne garder que chiffres + . + +/-
        import re
        txt2 = re.sub(r"[^0-9.\-+]", "", txt)
        try:
            return float(txt2)
        except Exception:
            raise ValueError(f"Valeur numérique invalide: {value}")


def _normalize_supplier_code(value) -> Optional[str]:
    """Retourne un supplier_code normalisé (None si vide/placeholder)."""
    if pd.isna(value):
        return None
    s = str(value).strip()
    if not s:
        return None
    if s.lower() in {"na", "n/a", "s/o", "so", "null", "none", "-", "—"}:
        return None
    return s


# --- Réconciliation d'unités (g/kg/l/ml/unit) ---

_MASS = {"g", "kg", "lb"}
_VOL = {"ml", "l"}
_COUNT = {"unit"}

def _unit_family(u: str) -> Optional[str]:
    if not u:
        return None
    if u in _MASS:
        return "mass"
    if u in _VOL:
        return "vol"
    if u in _COUNT:
        return "count"
    return None

def _canon_base(u: str) -> str:
    fam = _unit_family(u)
    if fam == "mass":
        return "g"
    if fam == "vol":
        return "ml"
    if fam == "count":
        return "unit"
    return ""

def _clean_unit_txt(u: str) -> str:
    u = (u or "").strip().lower()
    # synonymes fréquents → unit
    synonyms_to_unit = {"unite", "unité", "u", "pc", "piece", "pièce", "portion", "paquet", "caisse", "boite", "boîte", "bte", "sac", "sachet"}
    if u in synonyms_to_unit:
        return "unit"
    # synonymes mass/vol
    if u in {"gramme", "grammes", "gr"}:
        return "g"
    if u in {"kilogramme", "kilogrammes"}:
        return "kg"
    if u in {"millilitre", "millilitres"}:
        return "ml"
    if u in {"litre", "litres"}:
        return "l"
    # strip éventuels préfixes parasites
    if u.startswith(("/", "-", "—")):
        u = u.lstrip("/-—").strip()
    return u

def _reconcile_units(base_unit: str, pack_unit: str) -> Tuple[str, str]:
    bu = _clean_unit_txt(base_unit)
    pu = _clean_unit_txt(pack_unit)
    bu_c = _canon_base(bu)
    bf = _unit_family(bu_c)
    pf = _unit_family(pu)

    # Si base manquante, dériver depuis pack si possible, sinon unit
    if not bu_c:
        bu_c = _canon_base(pu) if pf else "unit"
        bf = _unit_family(bu_c)

    # Si pack manquant, le caler sur base
    if not pu:
        pu = bu_c
        pf = bf

    # Familles incohérentes → privilégier la famille du pack
    if bf in {"mass", "vol"} and pf in {"mass", "vol"} and bf != pf:
        bu_c = _canon_base(pu)
        bf = _unit_family(bu_c)

    # Pack en "unit" alors que base est mass/vol → mettre le pack sur la base
    if pf == "count" and bf in {"mass", "vol"}:
        pu = bu_c
        pf = bf

    # Base en "unit" et pack mass/vol → mettre la base sur le pack
    if bf == "count" and pf in {"mass", "vol"}:
        bu_c = _canon_base(pu)
        bf = _unit_family(bu_c)

    return bu_c or "unit", pu or bu_c or "unit"


# ------------------------- Parsing ingrédients -------------------------

def _parse_ingredient_rows(df: pd.DataFrame) -> tuple[List[dict], List[str], int]:
    """Retourne (rows, errors, ignored_count). Tolérant sur les cases vides."""
    entries: List[dict] = []
    errors: List[str] = []
    ignored = 0

    df = _normalize_columns(df, INGREDIENT_ALIASES)
    # Colonnes requises "structurellement" (mais valeurs peuvent être vides)
    required_cols = {"name", "base_unit", "pack_size", "pack_unit", "purchase_price"}
    missing = [col for col in required_cols if col not in df.columns]
    if missing:
        errors.append(
            "Colonnes manquantes pour les ingrédients: " + ", ".join(sorted(missing))
        )
        return ([], errors, 0)

    for idx, row in df.iterrows():
        line_no = idx + 2  # entête = ligne 1
        try:
            name = _coerce_str(row.get("name"))
            if not name:
                ignored += 1
                errors.append(f"Ligne {line_no}: nom vide → ignorée")
                continue

            # Unités : réconciliation + défauts
            base_unit_raw = _coerce_str(row.get("base_unit"))
            pack_unit_raw = _coerce_str(row.get("pack_unit"))
            base_unit, pack_unit = _reconcile_units(base_unit_raw, pack_unit_raw)

            # Quantités / prix avec défauts permissifs
            pack_size = _coerce_float(row.get("pack_size"))
            if pack_size is None or pack_size <= 0:
                pack_size = 1.0
            purchase_price = _coerce_float(row.get("purchase_price"))
            if purchase_price is None:
                purchase_price = 0.0
            if purchase_price < 0:
                raise ValueError("Prix d'achat invalide (négatif)")

            price_per_base = compute_price_per_base_unit(
                pack_size=float(pack_size),
                pack_unit=pack_unit,
                base_unit=base_unit,
                purchase_price=float(purchase_price),
            )

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
        except Exception as exc:  # noqa: BLE001
            errors.append(f"Ligne {line_no}: {exc}")
    return entries, errors, ignored


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


def _apply_ingredient_import(db: Session, rows: List[dict]) -> ImportResult:
    created = 0
    updated = 0
    supplier_cache: Dict[str, Supplier] = {}
    sql_errors: List[str] = []

    try:
        for payload in rows:
            supplier = _resolve_supplier(db, supplier_cache, payload["supplier"])

            # 🔧 IMPORTANT : ne plus utiliser func.lower(...) ici (accents non gérés par SQLite)
            name_key = (payload["name"] or "").strip()

            ingredient = (
                db.query(Ingredient)
                .filter(Ingredient.name == name_key)  # comparaison exacte (respecte les accents)
                .one_or_none()
            )

            if ingredient:
                updated += 1
            else:
                ingredient = Ingredient(name=name_key)
                db.add(ingredient)
                created += 1

            ingredient.category = payload["category"] or "Autre"
            ingredient.base_unit = payload["base_unit"]
            ingredient.pack_size = payload["pack_size"]
            ingredient.pack_unit = payload["pack_unit"]
            ingredient.purchase_price = payload["purchase_price"]
            ingredient.price_per_base_unit = payload["price_per_base_unit"]
            ingredient.supplier_id = supplier.id if supplier else None

            # On ne stocke jamais "" pour supplier_code : None → NULL en DB
            ingredient.supplier_code = _normalize_supplier_code(payload.get("supplier_code"))

        db.commit()
    except IntegrityError as exc:
        db.rollback()
        sql_errors.append(
            "Contrainte d'unicité violée. "
            "Vérifiez les doublons de nom d'ingrédient **exact** (accents inclus) ou les couples (fournisseur, code). "
            f"Détail : {exc.orig}"
        )
        return ImportResult(created=created, updated=updated, errors=sql_errors)
    except Exception as exc:
        db.rollback()
        sql_errors.append(f"Erreur d'import SQL : {exc}")
        return ImportResult(created=created, updated=updated, errors=sql_errors)

    auto_export(db, "ingredients")
    return ImportResult(created=created, updated=updated, errors=[])



# ------------------------- Parsing recettes -------------------------

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
            {
                "category": "",
                "servings": 1,
                "instructions": "",
                "items": [],
            },
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
        try:
            qty = _coerce_float(row.get("quantity"))
        except ValueError as exc:
            errors.append(f"Ligne {line_no}: {exc}")
            continue
        if qty is None:
            errors.append(f"Ligne {line_no}: quantité manquante")
            continue
        unit = normalize_unit(_coerce_str(row.get("unit")) or "g")
            ingredient = (
            db.query(Ingredient)
            .filter(Ingredient.name == ing_name.strip())  # comparaison exacte (accents respectés)
            .one_or_none()
)

        if not ingredient:
            errors.append(
                f"Ligne {line_no}: ingrédient inconnu '{(ing_name)}' (créez-le avant import)"
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
    try:
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
    except Exception as exc:
        db.rollback()
        return ImportResult(created=created, updated=updated, errors=[f"Erreur import recettes : {exc}"])

    auto_export(db, "recipes")
    auto_export(db, "recipe_items")
    return ImportResult(created=created, updated=updated, errors=[])


# ------------------------- Lecture CSV -------------------------

def _read_uploaded_csv(uploaded_file) -> pd.DataFrame:
    if uploaded_file is None:
        raise ValueError("Aucun fichier fourni")
    try:
        uploaded_file.seek(0)
    except Exception:  # pragma: no cover
        pass
    # Detection auto du séparateur + fallback encodage
    try:
        return pd.read_csv(uploaded_file, sep=None, engine="python")
    except UnicodeDecodeError:
        uploaded_file.seek(0)
        return pd.read_csv(uploaded_file, sep=None, engine="python", encoding="latin-1")


# ------------------------- UI Google Sheets -------------------------

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
                except Exception as exc:  # pragma: no cover
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
                except Exception as exc:  # pragma: no cover
                    st.error(f"Import échoué : {exc}")
                else:
                    st.success(f"{count} ligne(s) importée(s) depuis Google Sheets.")


# ------------------------- UI CSV -------------------------

def _render_csv_import_section(db: Session) -> None:
    st.subheader("Importer depuis un CSV")
    st.markdown(
        "Préparez un fichier CSV (séparateur autodétecté) avec les colonnes suivantes :"
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
            rows, parse_errors, ignored = _parse_ingredient_rows(df)
            if parse_errors:
                # On affiche toutes les erreurs/ignores (utiles pour correction)
                st.error("\n".join(parse_errors))
            if rows:
                with st.spinner("Import des ingrédients…"):
                    res = _apply_ingredient_import(db, rows)
                # on fusionne ignored dans le message final
                res.ignored += ignored
                st.success(f"Import ingrédients terminé : {res.as_message()}")
            elif not parse_errors:
                st.info("Aucune donnée valide à importer.")
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
            elif not parse_errors:
                st.info("Aucune recette valide à importer.")
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
