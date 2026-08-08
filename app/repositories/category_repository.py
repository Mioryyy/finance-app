from sqlalchemy import case, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.category import Category


async def get_categories_for_user(session: AsyncSession, user_id: int, type):
    order_key = case((Category.id == 11, 1), else_=0)
    stmt = (
        select(Category)
        .where(
            or_(Category.owner_id == None, Category.owner_id == user_id),
            Category.type == type,
        )
        .order_by(order_key, Category.id)
    )
    result = await session.execute(stmt)
    categories = result.scalars().all()
    return categories


async def get_or_create_default_category(session: AsyncSession, name: str, type: str):
    order_key = case((Category.id == 11, 1), else_=0)
    stmt = (
        select(Category)
        .where(Category.name == name, Category.owner_id == None, Category.type == type)
        .order_by(order_key, Category.id)
    )
    result = await session.execute(stmt)
    category = result.scalar_one_or_none()
    if category:
        return category
    new_category = Category(name=name, type=type)
    session.add(new_category)
    await session.commit()
    return new_category


async def get_category(session: AsyncSession, id: int):
    stmt = select(Category).where(Category.id == id)
    result = await session.execute(stmt)
    category = result.scalar_one()
    return category.name
