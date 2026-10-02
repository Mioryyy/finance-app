from app.models.account import Account
from app.repositories.account_repository import create_account, update_balance
from app.repositories.user_repository import get_or_create_user


async def test_database_connection(session):
    user, _ = await get_or_create_user(session, 12345)
    account = await create_account(session, user.id, "test", "cash", "USD")
    account_id = account.id
    session.expire_all()
    account = await session.get(Account, account_id)
    assert account.balance == 0
    await update_balance(session, account_id, 1000)
    session.expire_all()
    account = await session.get(Account, account_id)
    assert account.balance == 1000
    await update_balance(session, account_id, -100)
    session.expire_all()
    account = await session.get(Account, account_id)
    assert account.balance == 900
