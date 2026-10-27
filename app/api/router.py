from fastapi import APIRouter, HTTPException

from app import exceptions as exc
from app.api.schemas import TransactionCreate
from app.database import async_session_maker
from app.repositories.transaction_repository import (
    create_transaction,
    delete_transaction_by_id,
    get_transactions_for_user,
)

router = APIRouter()

NOT_ENOUGH_MONEY = "Недостаточно средств: баланс счёта ушёл бы в минус"


@router.get("/transactions")
async def get_transactions_api(account_id: int):
    async with async_session_maker() as session:
        transactions = await get_transactions_for_user(session, account_id)
    return transactions


@router.post("/transactions")
async def create_transaction_api(data: TransactionCreate):
    async with async_session_maker() as session:
        try:
            transaction = await create_transaction(
                session,
                data.account_id,
                data.category_id,
                data.description,
                data.amount,
                data.tx_type,
                data.date,
            )
        except exc.InsufficientFunds:
            raise HTTPException(status_code=409, detail=NOT_ENOUGH_MONEY) from None
        await session.commit()
        # commit делает объект устаревшим; перечитываем, пока сессия открыта,
        # иначе FastAPI упадёт при сериализации ответа
        await session.refresh(transaction)
    return transaction


@router.delete("/transactions/{transaction_id}")
async def delete_transaction_api(transaction_id: int, account_id: int):
    async with async_session_maker() as session:
        try:
            deleted = await delete_transaction_by_id(
                session, transaction_id, account_id
            )
        except exc.InsufficientFunds:
            raise HTTPException(status_code=409, detail=NOT_ENOUGH_MONEY) from None
        await session.commit()
    if not deleted:
        raise HTTPException(status_code=404, detail="Транзакция не найдена")
    return f"Транзакция {transaction_id} удалена"
