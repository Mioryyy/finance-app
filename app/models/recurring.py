from datetime import date
from decimal import Decimal

from sqlalchemy import ForeignKey, Integer, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class RecurringPayment(Base):
    """Регулярная операция: зарплата или подписка.

    Операцию бот сам не записывает: в день платежа он спрашивает человека
    («Добавить?») и пишет её только после подтверждения.

    Период (period):
    - month: каждый месяц в day_of_month (31-е в коротком месяце = последний день);
    - days: каждые interval_days дней от предыдущего платежа (30 дней это не месяц);
    - year: раз в год в day_of_month числа месяца anchor_month.
    """

    __tablename__ = "recurring_payments"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id"))
    category_id: Mapped[int] = mapped_column(ForeignKey("category.id"))
    tx_type: Mapped[str] = mapped_column(String(8))  # expense или income
    description: Mapped[str] = mapped_column(Text)
    amount: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    # день месяца для month и year; для days хранит день первого платежа
    day_of_month: Mapped[int] = mapped_column(Integer)
    # default - для новых объектов в Python, server_default - для старых строк
    period: Mapped[str] = mapped_column(
        String(8), default="month", server_default="month"
    )
    interval_days: Mapped[int | None] = mapped_column(Integer)  # только для days
    anchor_month: Mapped[int | None] = mapped_column(Integer)  # только для year
    # ближайшая дата платежа; после ответа человека сдвигается на период вперёд
    next_due: Mapped[date]
    # для какой next_due вопрос уже отправлен: не спрашиваем дважды
    prompted_due: Mapped[date | None]
