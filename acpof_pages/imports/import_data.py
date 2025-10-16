"""Outils d'import CSV pour les ingrédients et recettes."""
from __future__ import annotations

import math
from typing import Dict, List

import pandas as pd
import streamlit as st
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from db import Ingredient, Recipe, RecipeItem, SessionLocal, Supplier, init_db
from acpof_pages.logic import compute_price_per_base_unit
from units import normalize_unit

try:  # pragma: no cover - dépend d'une config externe
    from sheets_sync import auto_export  # type: ignore
except Exception:  # pragma: no cover - si l'export n'est pas configuré
    def auto_export(*_args, **_kwargs):
        """Fallback silencieux quand sheets_sync n'est pas disponible."""
        pass
