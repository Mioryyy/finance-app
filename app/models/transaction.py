from datetime import date
from decimal import Decimal

from sqlalchemy import Boolean, ForeignKey, Numeric, Text, false
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class Transaction(Base):
    __tablename__ = "transactions"

    id: Mapped[int] = mapped_column(primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id"))
    category_id: Mapped[int] = mapped_column(ForeignKey("category.id"))
    description: Mapped[str | None] = mapped_column(Text)
    amount: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    date: Mapped[date]
    # сохранена в быстром режиме, но категорию угадал не по истории:
    # попадёт в вечерний список «проверь»
    needs_review: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=false()
    )
