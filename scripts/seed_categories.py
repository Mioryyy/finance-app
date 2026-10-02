import asyncio

from app.database import async_session_maker
from app.models.user import User  # noqa: F401
from app.repositories.category_repository import get_or_create_default_category

DEFAULT_CATEGORIES = [
    "🍔 Еда и напитки",
    "🚕 Транспорт",
    "🎉 Развлечения",
    "🎮 Игры и подписки",
    "👟 Одежда и обувь",
    "📚 Учёба",
    "🎁 Подарки",
    "💊 Здоровье",
    "🎀 Красота",
    "🛒 Крупные покупки",
    "📦 Другое",
]
DEFAULT_INCOME_CATEGORIES = [
    "💰 Зарплата",
    "🎁 Подарок",
    "💳 Возврат долга",
    "📈 Подработка",
    "🎉 Другое",
]


async def main():
    async with async_session_maker() as session:
        for name in DEFAULT_CATEGORIES:
            await get_or_create_default_category(session, name, category_type="expense")
        for name in DEFAULT_INCOME_CATEGORIES:
            await get_or_create_default_category(session, name, category_type="income")
        await session.commit()


if __name__ == "__main__":
    asyncio.run(main())
