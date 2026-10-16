from decimal import Decimal

from pydantic import BaseModel
from datetime import date

class TransactionCreate(BaseModel):
    account_id: int
    category_id: int
    description: str
    amount: Decimal
    tx_type: str
    date: date