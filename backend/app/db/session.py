
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app.core.config import settings


def normalize_database_url(url: str) -> str:
    """Adapta la URL de PostgreSQL para usar Psycopg 3."""
    if url.startswith("postgres://"):
        url = url.replace(
            "postgres://",
            "postgresql+psycopg://",
            1,
        )
    elif url.startswith("postgresql://"):
        url = url.replace(
            "postgresql://",
            "postgresql+psycopg://",
            1,
        )

    return url


database_url = normalize_database_url(settings.database_url)

engine = create_engine(
    database_url,
    pool_size=settings.db_pool_size,
    max_overflow=settings.db_max_overflow,
    pool_pre_ping=True,
    pool_recycle=1800,
)

SessionLocal = sessionmaker(
    bind=engine,
    autoflush=False,
    expire_on_commit=False,
)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

