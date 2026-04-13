import enum
from sqlalchemy import String, ForeignKey, Boolean, Enum
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.db.base import Base
from datetime import datetime, timezone
from sqlalchemy import DateTime

class UserRole(str, enum.Enum):
    ADMIN = "admin"
    REQUESTOR = "requestor"
    APPROVER = "approver"
    ACCOUNTANT = "accountant"

class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    hashed_password: Mapped[str] = mapped_column(String(255))
    first_name: Mapped[str] = mapped_column(String(50))
    last_name: Mapped[str] = mapped_column(String(50))
    phone_number: Mapped[str] = mapped_column(String(20), nullable=True)
    role: Mapped[UserRole] = mapped_column(Enum(UserRole, native_enum=False), default=UserRole.REQUESTOR)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    
    # Foreign Keys
    org_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"))
    
    # Relationships
    organization: Mapped["Organization"] = relationship(back_populates="users")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), 
        default=lambda: datetime.now(timezone.utc)
    )



