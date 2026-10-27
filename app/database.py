import os

from dotenv import load_dotenv
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

load_dotenv()
db_password = os.getenv("DB_PASSWORD")
# локально база доступна на localhost, а в Docker — по имени сервиса из compose (db)
db_host = os.getenv("DB_HOST", "localhost")


class Base(DeclarativeBase):
    pass


DATABASE_URL = f"postgresql+asyncpg://postgres:{db_password}@{db_host}:5432/finance"

engine = create_async_engine(DATABASE_URL)
async_session_maker = async_sessionmaker(engine, class_=AsyncSession)
