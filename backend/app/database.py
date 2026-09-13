from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base
from .config import settings

# Postgres-only. SQLite is no longer supported.
if not settings.DATABASE_URL.startswith(("postgresql://", "postgres://", "postgresql+")):
    raise RuntimeError(
        "DATABASE_URL must be a PostgreSQL connection string "
        "(e.g. postgresql://postgres:postgres@localhost:5432/chatversio). "
        "SQLite is not supported."
    )

engine = create_engine(
    settings.DATABASE_URL,
    pool_pre_ping=True,
    pool_size=10,
    max_overflow=20,
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()