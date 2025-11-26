from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

SQLITE_DATABASE_URL = "sqlite:///./db.sqlite"

engine = create_engine(
    SQLITE_DATABASE_URL,
    connect_args={"check_same_thread": False},
    echo=False,
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)