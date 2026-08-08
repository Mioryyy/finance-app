from decimal import Decimal

from sqlalchemy import ForeignKey, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class Account(Base):

    __tablename__ = "accounts"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(20))
    balance: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    type: Mapped[str] = mapped_column(String(8))
    currency: Mapped[str] = mapped_column(String(5))
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
