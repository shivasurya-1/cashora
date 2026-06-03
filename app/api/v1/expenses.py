"""
/expenses/ router
General expense operations not tied to a specific role's sub-router.
"""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Optional

from app.core.security import get_current_user
from app.db.session import get_db
from app.models.expense import ExpenseRequest, ExpenseStatus

router = APIRouter(prefix="/expenses", tags=["expenses"])


class ProcessPaymentQRRequest(BaseModel):
    expense_id: int
    qr_image_url: str
    qr_data: Optional[str] = None


@router.post("/process-payment-qr")
async def process_payment_qr(
    payload: ProcessPaymentQRRequest,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """
    Record a QR-based payment reference against an expense.
    The QR image URL and optional decoded QR data are stored on the expense.
    """
    result = await db.execute(
        select(ExpenseRequest).where(
            ExpenseRequest.id == payload.expense_id,
            ExpenseRequest.org_id == current_user.org_id,
        )
    )
    expense = result.scalar_one_or_none()
    if not expense:
        raise HTTPException(status_code=404, detail="Expense not found.")

    if expense.status not in [ExpenseStatus.APPROVED, ExpenseStatus.AUTO_APPROVED]:
        raise HTTPException(
            status_code=400,
            detail=f"Cannot process QR payment. Expense status is '{expense.status.value}'.",
        )

    # Store QR image URL (reuse payment_qr_url field) and decoded data as transaction_reference
    expense.payment_qr_url = payload.qr_image_url
    if payload.qr_data:
        expense.transaction_reference = payload.qr_data[:100]  # truncate to column width

    await db.commit()
    await db.refresh(expense)

    return {
        "success": True,
        "expense_id": expense.id,
        "request_id": expense.request_id,
        "qr_image_url": expense.payment_qr_url,
        "qr_data": expense.transaction_reference,
        "status": expense.status.value,
    }
