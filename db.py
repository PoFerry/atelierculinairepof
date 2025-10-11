# db.py
from __future__ import annotations
from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker
import os

DB_PATH = os.environ.get("ACPOF_DB_PATH", "data.db")
DB_URL = os.environ.get("ACPOF_DB_URL")  # défini dans les Secrets Streamlit

if DB_URL and DB_URL.startswith("postgresql"):
    # Supabase (Postgres)
    engine = create_engine(
        DB_URL,
        echo=False,
        pool_pre_ping=True,
        pool_size=5,
        max_overflow=10,
        future=True,
    )
else:
    # Local (SQLite)
    engine = create_engine(
        f"sqlite:///{DB_PATH}",
        echo=False,
        future=True,
    )

SessionLocal = sessionmaker(bind=engine, expire_on_commit=False, future=True)
Base = declarative_base()

# ... (tes modèles inchangés) ...

def init_db():
    Base.metadata.create_all(bind=engine)
