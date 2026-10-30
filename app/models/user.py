from sqlalchemy import BigInteger, Boolean, ForeignKey, false, true
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    telegram_id: Mapped[int] = mapped_column(BigInteger, unique=True)
    active_account_id: Mapped[int | None] = mapped_column(ForeignKey("accounts.id"))
    # default — для новых объектов в Python (без него чтение после flush
    # пошло бы в базу и упало в async), server_default — для старых строк
    # «быстрый ввод»: трата сохраняется сразу, без окна подтверждения
    quick_entry: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=false()
    )
    # вечернее сообщение в 20:00: напоминание или список трат на проверку
    reminders: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default=true()
    )
