from fastapi import APIRouter
from decimal import Decimal

from app.database import async_session_maker
from app.repositories.transaction_repository import get_transactions_for_user, delete_transaction_by_id, \
    create_transaction

router = APIRouter()

@router.get("/transactions")
async def get_transactions_api(account_id: int):
    async with async_session_maker() as session:
        transactions = await get_transactions_for_user(session, account_id)
    return transactions

@router.post("/transactions")
async def create_transaction_api(account_id:int, category_id, description, amount: Decimal ,tx_type,tr_date = None):
    async with async_session_maker() as session:
        transaction = await create_transaction(session, account_id, category_id, description, amount, tx_type, tr_date)
        await session.commit()
    return transaction


@router.delete("/transactions/{transaction_id}")
async def delete_transaction_api(transaction_id):
    async with async_session_maker() as session:
        delete_transaction = await delete_transaction_by_id(session, transaction_id)
        await session.commit()
    if delete_transaction:
        return f"Транзакция {transaction_id} удалена"
