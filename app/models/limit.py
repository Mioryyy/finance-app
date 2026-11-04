from decimal import Decimal

from sqlalchemy import ForeignKey, Numeric, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class CategoryLimit(Base):
    """Месячный лимит трат на категорию в одной валюте."""

    __tablename__ = "category_limits"
    __table_args__ = (
        UniqueConstraint(
            "user_id", "category_id", "currency", name="uq_limit_user_category_currency"
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    category_id: Mapped[int] = mapped_column(ForeignKey("category.id"))
    currency: Mapped[str] = mapped_column(String(5))
    amount: Mapped[Decimal] = mapped_column(Numeric(10, 2))
