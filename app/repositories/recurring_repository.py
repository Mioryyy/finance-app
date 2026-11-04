from datetime import date

from sqlalchemy import delete, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.account import Account
from app.models.category import Category
from app.models.recurring import RecurringPayment
from app.models.user import User


async def count_user_recurring(session: AsyncSession, user_id):
    stmt = select(func.count(RecurringPayment.id)).where(
        RecurringPayment.user_id == user_id
    )
    return await session.scalar(stmt)


async def create_recurring(
    session: AsyncSession,
    user_id,
    account_id,
    category_id,
    tx_type,
    description,
    amount,
    day_of_month,
    next_due,
    period="month",
    interval_days=None,
    anchor_month=None,
):
    payment = RecurringPayment(
        user_id=user_id,
        account_id=account_id,
        category_id=category_id,
        tx_type=tx_type,
        description=description,
        amount=amount,
        day_of_month=day_of_month,
        period=period,
        interval_days=interval_days,
        anchor_month=anchor_month,
        next_due=next_due,
    )
    session.add(payment)
    await session.flush()
    return payment


async def get_user_recurring(session: AsyncSession, user_id):
    # (платёж, название категории, валюта счёта)
    stmt = (
        select(RecurringPayment, Category.name, Account.currency)
        .join(Category, RecurringPayment.category_id == Category.id)
        .join(Account, RecurringPayment.account_id == Account.id)
        .where(RecurringPayment.user_id == user_id)
        .order_by(RecurringPayment.id)
    )
    return (await session.execute(stmt)).all()


async def get_user_payment(session: AsyncSession, payment_id, user_id):
    # (платёж, название категории, валюта) одного платежа; чужой не найдёт:
    # id из кнопки не доверяем
    stmt = (
        select(RecurringPayment, Category.name, Account.currency)
        .join(Category, RecurringPayment.category_id == Category.id)
        .join(Account, RecurringPayment.account_id == Account.id)
        .where(RecurringPayment.id == payment_id, RecurringPayment.user_id == user_id)
    )
    return (await session.execute(stmt)).one_or_none()


async def set_recurring_amount(session: AsyncSession, payment, amount):
    # касается только будущих платежей: уже записанные операции не меняются
    payment.amount = amount
    await session.flush()


async def set_recurring_next_due(session: AsyncSession, payment, next_due):
    # prompted_due не трогаем: он станет неактуальным сам, и новую дату бот
    # спросит заново
    payment.next_due = next_due
    await session.flush()


async def get_recurring_for_update(session: AsyncSession, payment_id, user_id):
    # блокируем строку до commit: два быстрых нажатия «Добавить» не создадут
    # операцию дважды. id из кнопки не доверяем: платёж должен быть своим
    stmt = (
        select(RecurringPayment)
        .where(RecurringPayment.id == payment_id, RecurringPayment.user_id == user_id)
        .with_for_update()
    )
    return (await session.execute(stmt)).scalar_one_or_none()


async def delete_recurring(session: AsyncSession, payment_id, user_id) -> bool:
    result = await session.execute(
        delete(RecurringPayment).where(
            RecurringPayment.id == payment_id, RecurringPayment.user_id == user_id
        )
    )
    await session.flush()
    return result.rowcount > 0


async def due_payments(session: AsyncSession, today: date):
    # платежи, по которым пора спросить и вопрос ещё не отправлен:
    # (платёж, telegram_id, название категории, валюта)
    stmt = (
        select(RecurringPayment, User.telegram_id, Category.name, Account.currency)
        .join(User, RecurringPayment.user_id == User.id)
        .join(Category, RecurringPayment.category_id == Category.id)
        .join(Account, RecurringPayment.account_id == Account.id)
        .where(
            RecurringPayment.next_due <= today,
            or_(
                RecurringPayment.prompted_due.is_(None),
                RecurringPayment.prompted_due != RecurringPayment.next_due,
            ),
        )
        .order_by(RecurringPayment.id)
    )
    return (await session.execute(stmt)).all()


async def mark_prompted(session: AsyncSession, payment_id, due: date):
    payment = await session.get(RecurringPayment, payment_id)
    if payment is not None and payment.next_due == due:
        payment.prompted_due = due
    await session.flush()
