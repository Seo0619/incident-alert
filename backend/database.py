import os
from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base

# load .env
load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./incident.db")

# SQLite 특수 옵션 (멀티스레드 환경 대비)
connect_args = {}
if DATABASE_URL.startswith("sqlite"):
    connect_args = {"check_same_thread": False}

engine = create_engine(DATABASE_URL, connect_args=connect_args)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()


# FastAPI dependency: DB 세션 뽑아주고 끝나면 닫기
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
