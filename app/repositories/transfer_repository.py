from datetime import date

from sqlalchemy.ext.asyncio import AsyncSession

from app import exceptions as exc
from app.models.transfer import Transfer
from app.repositories.account_repository import (
    get_accounts_for_user,
    update_balance,
)


async def create_transfer(
    session: AsyncSession, user_id, from_account_id, to_account_id, amount
):
    accounts = await get_accounts_for_user(session, user_id)
    by_id = {a.id: a for a in accounts}
    if from_account_id not in by_id or to_account_id not in by_id:
        raise exc.ForeignAccount
    if from_account_id == to_account_id:
        raise exc.SameAccount
    from_account = by_id[from_account_id]
    to_account = by_id[to_account_id]
    if from_account.currency != to_account.currency:
        raise exc.DifferentCurrency
    if amount <= 0:
        raise exc.InvalidAmount
    # списание первым: если денег не хватит, update_balance кинет
    # InsufficientFunds раньше, чем перевод попадёт в сессию
    await update_balance(session, from_account_id, -amount)
    await update_balance(session, to_account_id, amount)
    new_transfer = Transfer(
        from_account_id=from_account_id,
        to_account_id=to_account_id,
        amount=amount,
        date=date.today(),
    )
    session.add(new_transfer)
    await session.flush()
    return new_transfer
