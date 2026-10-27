"""database.py — SQLAlchemy engine/session setup. DATABASE_URL overrides the default local SQLite file."""
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base

import os

SQLALCHEMY_DATABASE_URL = os.environ.get("DATABASE_URL", "sqlite:///./ed_monitor.db")

engine = create_engine(
    SQLALCHEMY_DATABASE_URL, connect_args={"check_same_thread": False}
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()

def get_db():
    """FastAPI dependency yielding a SQLAlchemy session that is always closed."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
