import enum
from sqlalchemy import String, ForeignKey, Float, DateTime, Enum, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.db.base import Base
import datetime


class PaymentMethod(str, enum.Enum):
    UPI = "upi"
    BANK_TRANSFER = "bank_transfer"
    CASH = "cash"
    CHEQUE = "cheque"
    NEFT = "neft"
    RTGS = "rtgs"
    IMPS = "imps"
    OTHER = "other"

class ExpenseStatus(str, enum.Enum):
    PENDING = "pending"
    AUTO_APPROVED = "auto_approved"
    APPROVED = "approved"
    REJECTED = "rejected"
    CLARIFICATION_REQUIRED = "clarification_required"
    CLARIFICATION_RESPONDED = "clarification_responded"
    PAID = "paid"

class ExpenseRequestType(str, enum.Enum):
    PRE_APPROVED = "pre_approved"   # Request amount first, then purchase after approval
    POST_APPROVED = "post_approved"  # Pay first, then upload bill for reimbursement

class ExpenseCategory(str, enum.Enum):
    TRAVEL = "travel"
    MEALS = "meals"
    SOFTWARE = "software"
    OFFICE_SUPPLIES = "office_supplies"
    OTHERS = "others"

class ExpenseRequest(Base):
    __tablename__ = "expense_requests"

    id: Mapped[int] = mapped_column(primary_key=True)
    request_id: Mapped[str] = mapped_column(String(20), unique=True, index=True) # Generated Code (e.g., EXP-1001)
    
    # Requestor Details
    request_type: Mapped[ExpenseRequestType] = mapped_column(Enum(ExpenseRequestType), default=ExpenseRequestType.PRE_APPROVED)
    amount: Mapped[float] = mapped_column(Float, nullable=False)
    purpose: Mapped[str] = mapped_column(String(255))
    description: Mapped[str] = mapped_column(Text, nullable=True)
    category: Mapped[ExpenseCategory] = mapped_column(Enum(ExpenseCategory))
    
    # Status & Workflow
    status: Mapped[ExpenseStatus] = mapped_column(Enum(ExpenseStatus), default=ExpenseStatus.PENDING)
    rejection_reason: Mapped[str] = mapped_column(Text, nullable=True)
    
    # Attachments
    receipt_url: Mapped[str] = mapped_column(String(500), nullable=True) # Bill/Receipt proof
    payment_qr_url: Mapped[str] = mapped_column(String(500), nullable=True) # QR code for payment
    payment_note: Mapped[str] = mapped_column(Text, nullable=True) # Note from requestor for accountant

    # Payment Settlement
    payment_method: Mapped[str] = mapped_column(String(50), nullable=True)  # stores lowercase value e.g. "bank_transfer"
    transaction_reference: Mapped[str] = mapped_column(String(100), nullable=True) # UPI ref / bank txn / cheque no.

    # Tracking
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime.datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())
    
    # Foreign Keys
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    org_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"))
    approver_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=True)

    # Relationships
    requestor: Mapped["User"] = relationship("User", foreign_keys=[user_id])
    approver: Mapped["User"] = relationship("User", foreign_keys=[approver_id])
    clarifications: Mapped[list["ClarificationHistory"]] = relationship(back_populates="expense_request")


class ClarificationHistory(Base):
    __tablename__ = "clarification_history"

    id: Mapped[int] = mapped_column(primary_key=True)
    expense_id: Mapped[int] = mapped_column(ForeignKey("expense_requests.id"))
    
    question: Mapped[str] = mapped_column(Text) # From Approver
    response: Mapped[str] = mapped_column(Text, nullable=True) # From Requestor
    
    asked_at: Mapped[datetime.datetime] = mapped_column(DateTime, server_default=func.now())
    responded_at: Mapped[datetime.datetime] = mapped_column(DateTime, nullable=True)

    expense_request: Mapped["ExpenseRequest"] = relationship(back_populates="clarifications")