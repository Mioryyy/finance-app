from sqlalchemy import delete, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.constants import DEFAULT_ACCOUNT_NAME
from app.models.account import Account
from app.models.category import Category
from app.models.transaction import Transaction
from app.models.transfer import Transfer
from app.models.user import User
from app.repositories.account_repository import create_account


async def get_or_create_user(session: AsyncSession, telegram_id: int):
    stmt = select(User).where(User.telegram_id == telegram_id)
    result = await session.execute(stmt)
    user = result.scalar_one_or_none()
    if user:
        return user, False
    new_user = User(telegram_id=telegram_id)
    session.add(new_user)
    await session.flush()
    return new_user, True


async def get_user(session: AsyncSession, telegram_id: int):
    # в отличие от get_or_create_user ничего не создаёт: нужен там, где
    # незнакомый человек не должен получить запись в базе (например, при удалении)
    result = await session.execute(select(User).where(User.telegram_id == telegram_id))
    return result.scalar_one_or_none()


async def set_active_account(session: AsyncSession, user, account_id: int):
    user.active_account_id = account_id
    await session.flush()


async def create_first_account(session: AsyncSession, user, currency: str):
    # первый счёт при /start; None, если счёт уже есть.
    # Блокируем строку пользователя до commit: второе одновременное нажатие
    # дождётся первого и увидит, что счёт уже создан
    await session.refresh(user, with_for_update=True)
    if user.active_account_id is not None:
        return None
    # тип card: у карты можно уйти в минус, поэтому первая трата
    # при нулевом балансе не упадёт с «не хватает денег»
    account = await create_account(
        session, user.id, DEFAULT_ACCOUNT_NAME, "card", currency
    )
    await set_active_account(session, user, account.id)
    return account


SETTINGS = ("quick_entry", "reminders")


async def toggle_setting(session: AsyncSession, user, name: str):
    # name приходит из кнопки: разрешаем только известные настройки
    if name not in SETTINGS:
        raise ValueError(name)
    setattr(user, name, not getattr(user, name))
    await session.flush()
    return getattr(user, name)


async def get_users_for_reminders(session: AsyncSession):
    # без счёта напоминать нечего: такой человек ещё не дошёл до первой траты
    stmt = select(User).where(
        User.reminders.is_(True), User.active_account_id.is_not(None)
    )
    result = await session.execute(stmt)
    return result.scalars().all()


async def disable_reminders(session: AsyncSession, user_ids):
    await session.execute(
        update(User).where(User.id.in_(user_ids)).values(reminders=False)
    )
    await session.flush()


def _account_ids(user_id: int):
    return select(Account.id).where(Account.owner_id == user_id)


async def count_user_data(session: AsyncSession, user_id: int):
    """Сколько чего будет удалено вместе с пользователем."""
    account_ids = _account_ids(user_id)

    async def count(stmt):
        return await session.scalar(stmt)

    return {
        "accounts": await count(
            select(func.count()).select_from(Account).where(Account.owner_id == user_id)
        ),
        "transactions": await count(
            select(func.count())
            .select_from(Transaction)
            .where(Transaction.account_id.in_(account_ids))
        ),
        "transfers": await count(
            select(func.count())
            .select_from(Transfer)
            .where(
                or_(
                    Transfer.from_account_id.in_(account_ids),
                    Transfer.to_account_id.in_(account_ids),
                )
            )
        ),
        "categories": await count(
            select(func.count())
            .select_from(Category)
            .where(Category.owner_id == user_id)
        ),
    }


async def delete_user_data(session: AsyncSession, user_id: int):
    """Удалить пользователя и всё, что ему принадлежит. Только flush, commit в хендлере.

    Порядок важен из-за внешних ключей: users.active_account_id ссылается на
    счёт, а счёт на владельца, поэтому сначала обнуляем активный счёт.
    Общие категории (owner_id IS NULL) не трогаем: они принадлежат всем.
    """
    account_ids = _account_ids(user_id)
    await session.execute(
        update(User).where(User.id == user_id).values(active_account_id=None)
    )
    await session.execute(
        delete(Transfer).where(
            or_(
                Transfer.from_account_id.in_(account_ids),
                Transfer.to_account_id.in_(account_ids),
            )
        )
    )
    await session.execute(
        delete(Transaction).where(Transaction.account_id.in_(account_ids))
    )
    await session.execute(delete(Account).where(Account.owner_id == user_id))
    await session.execute(delete(Category).where(Category.owner_id == user_id))
    await session.execute(delete(User).where(User.id == user_id))
    await session.flush()
