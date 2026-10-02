from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.category import Category


async def get_categories_for_user(session: AsyncSession, user_id: int, category_type):
    order_key = Category.name.endswith("Другое")
    stmt = (
        select(Category)
        .where(
            or_(Category.owner_id == None, Category.owner_id == user_id),
            Category.type == category_type,
        )
        .order_by(order_key, Category.id)
    )
    result = await session.execute(stmt)
    categories = result.scalars().all()
    return categories


async def get_or_create_default_category(
    session: AsyncSession, name: str, category_type: str
):
    order_key = Category.name.endswith("Другое")
    stmt = (
        select(Category)
        .where(
            Category.name == name,
            Category.owner_id == None,
            Category.type == category_type,
        )
        .order_by(order_key, Category.id)
    )
    result = await session.execute(stmt)
    category = result.scalar_one_or_none()
    if category:
        return category
    new_category = Category(name=name, type=category_type)
    session.add(new_category)
    await session.flush()
    return new_category


async def get_category(session: AsyncSession, category_id: int):
    stmt = select(Category).where(Category.id == category_id)
    result = await session.execute(stmt)
    category = result.scalar_one()
    return category.name
