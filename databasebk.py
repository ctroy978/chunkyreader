from sqlmodel import SQLModel, create_engine, Session

SQLITE_DATABASE_URL = "sqlite:///student_reader.db"
engine = create_engine(
    SQLITE_DATABASE_URL, connect_args={"check_same_thread": False}, echo=True
)


def create_db_and_tables():
    SQLModel.metadata.create_all(engine)


def get_session():
    with Session(engine) as session:
        yield session
