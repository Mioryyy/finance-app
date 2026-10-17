from datetime import date
from decimal import Decimal

from pydantic import BaseModel


class TransactionCreate(BaseModel):
    account_id: int
    category_id: int
    description: str
    amount: Decimal
    tx_type: str
    date: date