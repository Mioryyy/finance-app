from decimal import Decimal

from sqlalchemy import CheckConstraint, ForeignKey, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class Account(Base):
    __tablename__ = "accounts"
    # страховка на уровне базы: минус разрешён только картам
    # (правило совпадает с OVERDRAFT_ACCOUNT_TYPES в app/constants.py)
    __table_args__ = (
        CheckConstraint(
            "type = 'card' OR balance >= 0", name="ck_accounts_balance_non_negative"
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(20))
    balance: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    type: Mapped[str] = mapped_column(String(8))
    currency: Mapped[str] = mapped_column(String(5))
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
