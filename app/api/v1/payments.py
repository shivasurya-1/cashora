"""
/payments/ router
Handles manual payment recording, UPI initiation/confirmation, and history.
All endpoints require Accountant role.
"""
import uuid
import re
import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import get_current_user
from app.db.session import get_db
from app.models.expense import ExpenseRequest, ExpenseStatus
from app.models.payment import Payment
from app.models.user import UserRole

router = APIRouter(prefix="/payments", tags=["payments"])

# ---------- Schemas ----------

_VPA_RE = re.compile(r"^[a-zA-Z0-9.\-_]+@[a-zA-Z0-9]+$")


class RecordPaymentRequest(BaseModel):
    amount: float = Field(..., gt=0, description="Payment amount, must be positive")
    payment_method: str = Field(..., description="'UPI', 'CASH', or 'CUSTOM'")
    transaction_id: Optional[str] = None
    note: Optional[str] = None
    timestamp: Optional[datetime.datetime] = None

    @field_validator("payment_method")
    @classmethod
    def normalise_method(cls, v: str) -> str:
        allowed = {"upi", "cash", "custom"}
        if v.strip().lower() not in allowed:
            raise ValueError(f"payment_method must be one of: {', '.join(allowed)}")
        return v.strip().lower()


class InitiatePaymentRequest(BaseModel):
    request_id: str = Field(..., description="Expense request_id string (e.g. EXP-1001)")
    payee_vpa: str = Field(..., description="UPI VPA of the payee, e.g. user@upi")
    amount: float = Field(..., gt=0)
    payee_name: Optional[str] = None
    transaction_note: Optional[str] = Field(default=None, max_length=500)

    @field_validator("payee_vpa")
    @classmethod
    def validate_vpa(cls, v: str) -> str:
        if not _VPA_RE.match(v.strip()):
            raise ValueError("Invalid UPI VPA format. Expected format: handle@bank")
        return v.strip()


class ConfirmPaymentRequest(BaseModel):
    payment_id: str
    status: str = Field(..., description="'completed' or 'failed'")
    upi_txn_id: Optional[str] = None
    error_message: Optional[str] = None

    @field_validator("status")
    @classmethod
    def validate_status(cls, v: str) -> str:
        allowed = {"completed", "failed"}
        if v.strip().lower() not in allowed:
            raise ValueError(f"status must be one of: {', '.join(allowed)}")
        return v.strip().lower()


def _require_accountant(current_user):
    if current_user.role != UserRole.ACCOUNTANT:
        raise HTTPException(status_code=403, detail="Access denied. Accountant role required.")


# ---------- Endpoints ----------

@router.post("/record")
async def record_payment(
    payload: RecordPaymentRequest,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Record a manual payment (cash, UPI, or custom)."""
    _require_accountant(current_user)

    new_payment = Payment(
        payment_id=f"PAY-{uuid.uuid4().hex[:10].upper()}",
        org_id=current_user.org_id,
        amount=payload.amount,
        payment_method=payload.payment_method,
        transaction_id=payload.transaction_id,
        note=payload.note,
        status="completed",
        recorded_by_user_id=current_user.id,
        payment_timestamp=payload.timestamp or datetime.datetime.now(datetime.timezone.utc),
    )
    db.add(new_payment)
    await db.commit()
    await db.refresh(new_payment)

    return {
        "success": True,
        "payment_id": new_payment.payment_id,
        "amount": new_payment.amount,
        "payment_method": new_payment.payment_method,
        "status": new_payment.status,
        "payment_timestamp": new_payment.payment_timestamp.isoformat(),
    }


@router.get("/history")
async def get_payment_history(
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Return all payment records for the current user's organisation."""
    _require_accountant(current_user)

    result = await db.execute(
        select(Payment)
        .where(Payment.org_id == current_user.org_id)
        .order_by(Payment.payment_timestamp.desc())
    )
    payments = result.scalars().all()

    return [
        {
            "id": p.id,
            "payment_id": p.payment_id,
            "amount": p.amount,
            "payment_method": p.payment_method,
            "transaction_id": p.transaction_id,
            "note": p.note,
            "status": p.status,
            "payee_vpa": p.payee_vpa,
            "payee_name": p.payee_name,
            "upi_txn_id": p.upi_txn_id,
            "payment_timestamp": p.payment_timestamp.isoformat() if p.payment_timestamp else None,
            "expense_id": p.expense_id,
        }
        for p in payments
    ]


@router.post("/initiate")
async def initiate_payment(
    payload: InitiatePaymentRequest,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """
    Initiate a UPI payment for an approved expense request.
    Records the intent in the DB with status='pending'.
    """
    _require_accountant(current_user)

    # Resolve expense by request_id string
    result = await db.execute(
        select(ExpenseRequest).where(
            ExpenseRequest.request_id == payload.request_id,
            ExpenseRequest.org_id == current_user.org_id,
        )
    )
    expense = result.scalar_one_or_none()
    if not expense:
        raise HTTPException(status_code=404, detail=f"Expense '{payload.request_id}' not found.")
    if expense.status not in [ExpenseStatus.APPROVED, ExpenseStatus.AUTO_APPROVED]:
        raise HTTPException(
            status_code=400,
            detail=f"Cannot initiate payment. Expense status is '{expense.status.value}'.",
        )

    payment_id = f"UPAY-{uuid.uuid4().hex[:10].upper()}"
    new_payment = Payment(
        payment_id=payment_id,
        org_id=current_user.org_id,
        expense_id=expense.id,
        amount=payload.amount,
        payment_method="upi",
        payee_vpa=payload.payee_vpa,
        payee_name=payload.payee_name,
        transaction_note=payload.transaction_note,
        status="pending",
        recorded_by_user_id=current_user.id,
        payment_timestamp=datetime.datetime.now(datetime.timezone.utc),
    )
    db.add(new_payment)
    await db.commit()
    await db.refresh(new_payment)

    return {
        "payment_id": new_payment.payment_id,
        "expense_id": expense.id,
        "request_id": expense.request_id,
        "amount": new_payment.amount,
        "payee_vpa": new_payment.payee_vpa,
        "payee_name": new_payment.payee_name,
        "status": new_payment.status,
        "initiated_at": new_payment.payment_timestamp.isoformat(),
    }


@router.post("/confirm")
async def confirm_payment(
    payload: ConfirmPaymentRequest,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Confirm or fail a previously initiated UPI payment."""
    _require_accountant(current_user)

    result = await db.execute(
        select(Payment).where(
            Payment.payment_id == payload.payment_id,
            Payment.org_id == current_user.org_id,
        )
    )
    payment = result.scalar_one_or_none()
    if not payment:
        raise HTTPException(status_code=404, detail="Payment record not found.")

    payment.status = payload.status
    payment.upi_txn_id = payload.upi_txn_id
    payment.error_message = payload.error_message

    # If confirmed, mark the linked expense as PAID
    if payload.status == "completed" and payment.expense_id:
        exp_result = await db.execute(
            select(ExpenseRequest).where(ExpenseRequest.id == payment.expense_id)
        )
        expense = exp_result.scalar_one_or_none()
        if expense and expense.status in [ExpenseStatus.APPROVED, ExpenseStatus.AUTO_APPROVED]:
            expense.status = ExpenseStatus.PAID
            expense.transaction_reference = payload.upi_txn_id

    await db.commit()
    await db.refresh(payment)

    return {
        "success": True,
        "payment_id": payment.payment_id,
        "status": payment.status,
        "upi_txn_id": payment.upi_txn_id,
        "error_message": payment.error_message,
    }


@router.get("/completed")
async def get_completed_payments(
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Return all completed payment records for the organisation."""
    _require_accountant(current_user)

    result = await db.execute(
        select(Payment).where(
            Payment.org_id == current_user.org_id,
            Payment.status == "completed",
        ).order_by(Payment.payment_timestamp.desc())
    )
    payments = result.scalars().all()

    return {
        "payments": [
            {
                "id": p.id,
                "payment_id": p.payment_id,
                "amount": p.amount,
                "payment_method": p.payment_method,
                "transaction_id": p.transaction_id,
                "upi_txn_id": p.upi_txn_id,
                "payee_vpa": p.payee_vpa,
                "payee_name": p.payee_name,
                "note": p.note,
                "expense_id": p.expense_id,
                "payment_timestamp": p.payment_timestamp.isoformat() if p.payment_timestamp else None,
            }
            for p in payments
        ]
    }
