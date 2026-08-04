from sqlalchemy import and_, case, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.category import Category


async def get_categories_for_user(session: AsyncSession, user_id: int):
    order_key = case((Category.id == 11, 1), else_=0)
    stmt = (
        select(Category)
        .where(or_(Category.owner_id == None, Category.owner_id == user_id))
        .order_by(order_key, Category.id)
    )
    result = await session.execute(stmt)
    categories = result.scalars().all()
    return categories


async def get_or_create_default_category(session: AsyncSession, name: str):
    order_key = case((Category.id == 11, 1), else_=0)
    stmt = (
        select(Category)
        .where(and_(Category.name == name, Category.owner_id == None))
        .order_by(order_key, Category.id)
    )
    result = await session.execute(stmt)
    category = result.scalar_one_or_none()
    if category:
        return category
    new_category = Category(name=name)
    session.add(new_category)
    await session.commit()
    return new_category
