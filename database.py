from sqlmodel import SQLModel, create_engine, Session
import os
from dotenv import load_dotenv
from typing import Generator
from urllib.parse import urlparse

# Load environment variables
load_dotenv()


def get_database_url() -> str:
    """Construct the database URL for Turso"""
    database_url = os.getenv("TURSO_DATABASE_URL")
    auth_token = os.getenv("TURSO_AUTH_TOKEN")

    if not database_url or not auth_token:
        raise EnvironmentError(
            "Turso database credentials not found. Please set TURSO_DATABASE_URL and TURSO_AUTH_TOKEN."
        )

    # Parse components
    parsed = urlparse(database_url)

    # Get hostname and database path, removing any protocol prefix
    hostname = parsed.netloc or database_url.split("/")[0]

    # Construct SQLAlchemy URL
    url = f"sqlite+libsql://{hostname}?authToken={auth_token}"
    return url


# Create the database URL and engine
DATABASE_URL = get_database_url()
engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False, "timeout": 30},
    pool_pre_ping=True,
    pool_recycle=3600,
)


def create_db_and_tables() -> None:
    """Create all tables defined in SQLModel metadata"""
    SQLModel.metadata.create_all(engine)


def get_session() -> Generator[Session, None, None]:
    """Get a database session"""
    session = Session(engine)
    try:
        yield session
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
