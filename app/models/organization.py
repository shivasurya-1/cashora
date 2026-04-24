from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy import String, DateTime, Float, func
from app.db.base import Base # We will create base.py next
import datetime

class Organization(Base):
    __tablename__ = "organizations"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    org_code: Mapped[str] = mapped_column(String(20), unique=True, index=True) # Unique identifier
    deemed_approval_limit: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)  # Auto-approve if amount <= this
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime, server_default=func.now())

    # Relationship to users
    users: Mapped[list["User"]] = relationship(back_populates="organization")
    departments: Mapped[list["Department"]] = relationship(back_populates="organization")