"""Outils d'import CSV pour les ingrédients et recettes."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional, Tuple

import pandas as pd
import streamlit as st
from sqlalchemy import func  # gardé pour d'autres usages
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


# Alias de colonnes acceptés (en minuscules déjà normalisés)
INGREDIENT_ALIASES = {
    "name": {"name", "nom"},
    "category": {"category", "categorie", "catégorie"},
    "base_unit": {"base_unit", "unite_base", "unité_base", "base"},
    "pack_size": {"pack_size", "format", "taille_colis", "format_achat"},
    "pack_unit": {"pack_unit", "unite_format", "unité_format", "format_unite"},
    "purchase_price": {"purchase_price", "prix_achat", "prix"},
    "supplier": {"supplier", "fournisseur"},
    "supplier_code": {"supplier_code", "code_fournisseur", "code"},
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


def _normalize_columns(df: pd.DataFrame, aliases: Dict[str, Iterable[str]]) -> pd.DataFrame:
    columns = {c: c.strip().lower() for c in df.columns}
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
    """Convertit un texte FR/EN en float. Retourne None si vide."""
    if pd.isna(value):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    txt = str(value).strip()
    if not txt:
        return None
    # espaces fines etc.
    txt = txt.replace("\u00A0", "").replace("\u202F", "").replace(" ", "")
    # séparateurs FR
    if "," in txt and "." in txt:
        # si la virgule est après le point, on suppose 1.234,56 → 1234.56
        if txt.rfind(",") > txt.rfind("."):
            txt = txt.replace(".", "").replace(",", ".")
        else:
            txt = txt.replace(",", "")
    elif "," in txt:
        txt = txt.replace(",", ".")
    # monnaies éventuelles
    for sym in ("$", "€", "£"):
        txt = txt.replace(sym, "")
    try:
        return float(txt)
    except ValueError:
        raise ValueError(f"Valeur numérique invalide: {value}")


def _normalize_supplier_code(code: Optional[str]) -> Optional[str]:
    """
    Normalise le code fournisseur :
    - vide/blank -> None (NULL en DB)
    - sinon chaîne trimée
    """
    if code is None:
        return None
    code = str(code).strip()
    return code or None


def _resolve_supplier(db: Session, cache: Dict[str, Supplier], name: str) -> Supplier | None:
    """Résout/crée un fournisseur par égalité exacte (accents respectés)."""
    if not name:
        return None
    key = name.strip()
    cache_key = key  # on garde la casse/accents pour éviter les collisions
    if cache_key in cache:
        return cache[cache_key]

    # Comparaison EXACTE (pas de func.lower: SQLite gère mal les accents)
    supplier = (
        db.query(Supplier)
        .filter(Supplier.name == key)
        .one_or_none()
    )
    if not supplier:
        supplier = Supplier(name=key)
        db.add(supplier)
        db.flush()
    cache[cache_key] = supplier
    return supplier


def _parse_ingredient_rows(df: pd.DataFrame) -> tuple[List[dict], List[str]]:
    entries: List[dict] = []
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
                raise ValueError("Nom requis")

            # Normalisations d'unités (fonction de votre projet)
            base_unit = normalize_unit(_coerce_str(row.get("base_unit")) or "")
            if not base_unit:
                raise ValueError("Unité de base manquante")

            pack_unit = normalize_unit(_coerce_str(row.get("pack_unit")) or base_unit)

            pack_size = _coerce_float(row.get("pack_size"))
            purchase_price = _coerce_float(row.get("purchase_price"))
            if pack_size is None or pack_size <= 0:
                raise ValueError("Format d'achat invalide")
            if purchase_price is None or purchase_price < 0:
                raise ValueError("Prix d'achat invalide")

            price_per_base = compute_price_per_base_unit(
                pack_size=pack_size,
                pack_unit=pack_unit,
                base_unit=base_unit,
                purchase_price=purchase_price,
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
        except Exception as exc:  # noqa: BLE001 - on veut capter toute erreur ici
            errors.append(f"Ligne {line_no}: {exc}")
    return entries, errors


def _apply_ingredient_import(db: Session, rows: List[dict]) -> ImportResult:
    """
    Import ingrédients avec :
    - comparaison EXACTE sur le nom (accents respectés)
    - supplier_code vide -> NULL
    - si (supplier_id, supplier_code) est déjà pris par un autre ingrédient, on désactive le code (NULL) pour la ligne courante
      afin d'éviter la violation UNIQUE, et on poursuit l'import.
    """
    created = 0
    updated = 0
    supplier_cache: Dict[str, Supplier] = {}
    sql_errors: List[str] = []

    try:
        for payload in rows:
            # Résolution fournisseur (égalité exacte)
            supplier = _resolve_supplier(db, supplier_cache, payload.get("supplier", ""))

            # Recherche par NOM exact (évite les faux 'non trouvés' liés aux accents)
            name_key = (payload.get("name") or "").strip()
            ingredient = (
                db.query(Ingredient)
                .filter(Ingredient.name == name_key)
                .one_or_none()
            )

            if ingredient:
                updated += 1
            else:
                ingredient = Ingredient(name=name_key)
                db.add(ingredient)
                created += 1

            # Champs simples
            ingredient.category = (payload.get("category") or "Autre")
            ingredient.base_unit = payload["base_unit"]
            ingredient.pack_size = payload["pack_size"]
            ingredient.pack_unit = payload["pack_unit"]
            ingredient.purchase_price = payload["purchase_price"]
            ingredient.price_per_base_unit = payload["price_per_base_unit"]

            # Fournisseur / code
            ingredient.supplier_id = supplier.id if supplier else None

            # Normaliser le code : "" -> None (NULL)
            scode = _normalize_supplier_code(payload.get("supplier_code"))

            if ingredient.supplier_id is not None and scode:
                # Vérifier si ce (supplier_id, supplier_code) est déjà utilisé par UN AUTRE ingrédient
                existing_same_code = (
                    db.query(Ingredient)
                    .filter(
                        Ingredient.supplier_id == ingredient.supplier_id,
                        Ingredient.supplier_code == scode,
                    )
                    .one_or_none()
                )
                if existing_same_code and existing_same_code.name != ingredient.name:
                    # Code déjà pris par un autre produit -> on désactive le code pour cette ligne
                    scode = None  # évite la violation UNIQUE

            ingredient.supplier_code = scode  # None -> NULL en DB

        db.commit()

    except IntegrityError as exc:
        db.rollback()
        sql_errors.append(
            "Violation de contrainte UNIQUE malgré la résolution automatique des codes.\n"
            "Vérifiez :\n"
            "- Les doublons exacts de *nom d'ingrédient* (accents inclus)\n"
            "- Les doublons (fournisseur, code) au sein du fichier lui-même\n"
            f"Détail SQL : {exc.orig}"
        )
        return ImportResult(created=created, updated=updated, errors=sql_errors)
    except Exception as exc:
        db.rollback()
        sql_errors.append(f"Erreur d'import SQL : {exc}")
        return ImportResult(created=created, updated=updated, errors=sql_errors)

    auto_export(db, "ingredients")
    return ImportResult(created=created, updated=updated, errors=[])

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

        # IMPORTANT : comparaison exacte, pas de func.lower (accents respectés)
        ingredient = (
            db.query(Ingredient)
            .filter(Ingredient.name == ing_name.strip())
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
    try:
        for name, payload in recipes.items():
            # IMPORTANT : comparaison exacte sur le nom de recette
            name_key = (name or "").strip()
            recipe = (
                db.query(Recipe)
                .filter(Recipe.name == name_key)
                .one_or_none()
            )
            if recipe:
                updated += 1
            else:
                recipe = Recipe(name=name_key)
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


def _read_uploaded_csv(uploaded_file) -> pd.DataFrame:
    if uploaded_file is None:
        raise ValueError("Aucun fichier fourni")
    try:
        uploaded_file.seek(0)
    except Exception:  # pragma: no cover
        pass
    try:
        return pd.read_csv(uploaded_file)
    except UnicodeDecodeError:
        uploaded_file.seek(0)
        return pd.read_csv(uploaded_file, encoding="latin-1")


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
                except Exception as exc:  # pragma: no cover - dépend de l'API externe
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
                except Exception as exc:  # pragma: no cover - dépend API
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
                if res.errors:
                    st.error("\n".join(res.errors))
                else:
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
                if res.errors:
                    st.error("\n".join(res.errors))
                else:
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
