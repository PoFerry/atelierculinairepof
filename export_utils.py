from __future__ import annotations
import os, pandas as pd
from datetime import datetime
EXPORT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "exports"))
def ensure_export_dir():
    os.makedirs(EXPORT_DIR, exist_ok=True); return EXPORT_DIR
def export_csv(df: "pd.DataFrame", prefix: str) -> str:
    ensure_export_dir()
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    path = os.path.join(EXPORT_DIR, f"{prefix}_{ts}.csv")
    df.to_csv(path, index=False, encoding="utf-8")
    return path
