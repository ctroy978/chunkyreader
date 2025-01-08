from sqlmodel import SQLModel, create_engine, Session
import os
from dotenv import load_dotenv
from urllib.parse import urlparse

# Load environment variables
load_dotenv()

# Get Turso credentials from environment
TURSO_DATABASE_URL = os.getenv("TURSO_DATABASE_URL")
TURSO_AUTH_TOKEN = os.getenv("TURSO_AUTH_TOKEN")

if not TURSO_DATABASE_URL or not TURSO_AUTH_TOKEN:
    raise EnvironmentError(
        "Turso database credentials not found in environment variables"
    )

# Parse the Turso URL to get the hostname and path
parsed_url = urlparse(TURSO_DATABASE_URL)
hostname = parsed_url.netloc
dbname = parsed_url.path.lstrip("/")

# Construct the database URL for Turso in the correct format
# Note: Using sqlite+libsql:// as the protocol
DATABASE_URL = f"sqlite+libsql://{hostname}/{dbname}?authToken={TURSO_AUTH_TOKEN}"

# Create engine with same settings as before
engine = create_engine(
    DATABASE_URL, connect_args={"check_same_thread": False}, echo=True
)


def create_db_and_tables():
    """Create all tables defined in SQLModel metadata"""
    SQLModel.metadata.create_all(engine)


def get_session():
    """Dependency function to get a database session"""
    with Session(engine) as session:
        yield session
