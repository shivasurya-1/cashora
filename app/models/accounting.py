import datetime
from typing import Optional
from sqlalchemy import Date, DateTime, Float, ForeignKey, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.db.base import Base


class DailyBalance(Base):
    __tablename__ = "daily_balances"
    __table_args__ = (
        UniqueConstraint("org_id", "balance_date", name="uq_daily_balances_org_date"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    org_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), nullable=False, index=True)
    balance_date: Mapped[datetime.date] = mapped_column(Date, nullable=False, index=True)
    opening_balance: Mapped[float] = mapped_column(Float, nullable=False)
    amount_in: Mapped[float] = mapped_column(Float, nullable=False, default=0.0, server_default="0")
    note: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    updated_by_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime.datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())

    updated_by: Mapped["User"] = relationship("User", foreign_keys=[updated_by_user_id])
