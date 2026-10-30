import os

import pytest
import pytest_asyncio
from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage
from dotenv import load_dotenv
from flow_helpers import TG_ID, Client, FakeSession
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.bot.handlers import (
    account_edit,
    accounts,
    add_category,
    admin,
    cancel,
    delete_data,
    feedback,
    review,
    settings,
    start,
    transaction,
)
from app.database import Base
from app.models.account import Account  # noqa: F401
from app.models.category import Category  # noqa: F401
from app.models.transaction import Transaction  # noqa: F401
from app.models.transfer import Transfer  # noqa: F401
from app.models.user import User  # noqa: F401
from app.repositories import category_repository
from app.repositories.account_repository import create_account
from app.repositories.category_repository import get_or_create_default_category
from app.repositories.user_repository import get_or_create_user, set_active_account

load_dotenv()
db_password = os.getenv("DB_PASSWORD")

TEST_DATABASE_URL = (
    f"postgresql+asyncpg://postgres:{db_password}@localhost:5432/finance_test"
)
assert TEST_DATABASE_URL.endswith("finance_test")


@pytest.fixture(autouse=True)
def _no_ai_by_default(monkeypatch):
    # .env подгружается и в тестах: без этого они ходили бы в настоящий Groq.
    # Тесты ИИ задают ключ сами и подменяют сетевой вызов
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    # то же для ADMIN_CHAT_ID и счётчика «когда последний раз слали отзыв»:
    # тесты не должны зависеть от .env разработчика и друг от друга
    monkeypatch.delenv("ADMIN_CHAT_ID", raising=False)
    feedback.last_sent.clear()


@pytest_asyncio.fixture
async def session_maker():
    # для тестов хендлеров: они сами открывают сессии, поэтому нужна фабрика,
    # а не одна готовая сессия. Работает с той же отдельной БД finance_test
    engine = create_async_engine(TEST_DATABASE_URL)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield async_sessionmaker(engine, class_=AsyncSession)
    async with engine.begin() as conn:
        await conn.execute(text("DROP SCHEMA public CASCADE"))
        await conn.execute(text("CREATE SCHEMA public"))
    await engine.dispose()


@pytest_asyncio.fixture
async def session():
    engine = create_async_engine(TEST_DATABASE_URL)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async_session_maker = async_sessionmaker(engine, class_=AsyncSession)
    async with async_session_maker() as session:
        yield session

    async with engine.begin() as conn:
        await conn.execute(text("DROP SCHEMA public CASCADE"))
        await conn.execute(text("CREATE SCHEMA public"))
    await engine.dispose()


@pytest_asyncio.fixture
async def client(session_maker, monkeypatch):
    # хендлеры сами открывают сессии: направляем их в тестовую базу
    for module in (
        transaction,
        add_category,
        delete_data,
        settings,
        review,
        start,
        account_edit,
        accounts,
        admin,
        category_repository,
    ):
        monkeypatch.setattr(module, "async_session_maker", session_maker)

    # роутеры живут на уровне модуля и привязываются к диспетчеру один раз;
    # порядок как в боевом main.py: delete_data раньше остальных
    routers = (
        cancel.router,
        delete_data.router,
        feedback.router,
        admin.router,
        settings.router,
        review.router,
        account_edit.router,
        accounts.router,
        start.router,
        add_category.router,
        transaction.router,
    )
    for router in routers:
        router._parent_router = None
    dp = Dispatcher(storage=MemoryStorage())
    for router in routers:
        dp.include_router(router)

    fake = FakeSession()
    bot = Bot(token="42:" + "A" * 35, session=fake)
    yield Client(dp, bot, fake)
    for router in routers:
        router._parent_router = None


@pytest_asyncio.fixture
async def world(session_maker):
    """Пользователь с картой и двумя общими категориями расходов."""
    async with session_maker() as session:
        user, _ = await get_or_create_user(session, TG_ID)
        card = await create_account(session, user.id, "Карта", "card", "BYN")
        await set_active_account(session, user, card.id)
        food = await get_or_create_default_category(session, "🍔 Еда", "expense")
        fun = await get_or_create_default_category(session, "🎉 Развлечения", "expense")
        # id берём до commit: после него объекты устаревают
        ids = {"user": user.id, "card": card.id, "food": food.id, "fun": fun.id}
        await session.commit()
        return ids
