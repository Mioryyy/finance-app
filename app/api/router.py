from fastapi import APIRouter

from app.api.schemas import TransactionCreate
from app.database import async_session_maker
from app.repositories.transaction_repository import (
    create_transaction,
    delete_transaction_by_id,
    get_transactions_for_user,
)

router = APIRouter()


@router.get("/transactions")
async def get_transactions_api(account_id: int):
    async with async_session_maker() as session:
        transactions = await get_transactions_for_user(session, account_id)
    return transactions


@router.post("/transactions")
async def create_transaction_api(data: TransactionCreate):
    async with async_session_maker() as session:
        transaction = await create_transaction(
            session,
            data.account_id,
            data.category_id,
            data.description,
            data.amount,
            data.tx_type,
            data.date,
        )
        await session.commit()
    return transaction


@router.delete("/transactions/{transaction_id}")
async def delete_transaction_api(transaction_id):
    async with async_session_maker() as session:
        delete_transaction = await delete_transaction_by_id(session, transaction_id)
        await session.commit()
    if delete_transaction:
        return f"Транзакция {transaction_id} удалена"
