from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy import func
from sqlalchemy.orm import selectinload
from typing import Optional
from pydantic import BaseModel
from app.db.session import get_db
from app.models.expense import ExpenseRequest, ExpenseStatus, PaymentMethod
from app.models.user import UserRole
from app.core.security import get_current_user
from app.core.config import settings
from app.schemas.expense import PaginatedExpenses


class MarkAsPaidRequest(BaseModel):
    payment_method: Optional[PaymentMethod] = None
    transaction_reference: Optional[str] = None
    payment_note: Optional[str] = None

router = APIRouter(prefix="/accountant", tags=["accountant"])


@router.get("/payment-methods")
async def get_payment_methods():
    """Return all valid payment method options for frontend dropdowns."""
    return [
        {"value": "upi",           "label": "UPI"},
        {"value": "bank_transfer", "label": "Bank Transfer"},
        {"value": "cash",          "label": "Cash"},
        {"value": "cheque",        "label": "Cheque"},
        {"value": "neft",          "label": "NEFT"},
        {"value": "rtgs",          "label": "RTGS"},
        {"value": "imps",          "label": "IMPS"},
        {"value": "other",         "label": "Other"},
    ]


@router.get("/dashboard")
async def get_financial_summary(db: AsyncSession = Depends(get_db)):
    # Calculate Total Spend (Amount Out) for PAID expenses
    spend_query = select(func.sum(ExpenseRequest.amount)).where(
        ExpenseRequest.status == ExpenseStatus.PAID
    )
    # Calculate Pending Payments (Approved but not PAID)
    pending_query = select(func.count(ExpenseRequest.id)).where(
        ExpenseRequest.status.in_([ExpenseStatus.APPROVED, ExpenseStatus.AUTO_APPROVED])
    )
    
    total_spend = (await db.execute(spend_query)).scalar() or 0
    pending_count = (await db.execute(pending_query)).scalar() or 0
    
    return {
        "amount_out": total_spend,
        "pending_payments": pending_count,
        "opening_balance": 100000.00, # Example static value
    }

@router.post("/process-payout")
async def process_payout(
    expense_id: int,
    reference_number: Optional[str] = None,
    accountant_note: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """Mark an expense as PAID manually."""
    # 0. Role Check
    if current_user.role != UserRole.ACCOUNTANT:
        raise HTTPException(status_code=403, detail="Only Accountants can process payouts.")

    # 1. Verify Expense is in APPROVED/AUTO_APPROVED state
    query = select(ExpenseRequest).where(
        ExpenseRequest.id == expense_id,
        ExpenseRequest.org_id == current_user.org_id
    )
    result = await db.execute(query)
    expense = result.scalar_one_or_none()
    
    if not expense:
        raise HTTPException(status_code=404, detail="Expense not found")
        
    if expense.status not in [ExpenseStatus.APPROVED, ExpenseStatus.AUTO_APPROVED]:
        raise HTTPException(status_code=400, detail=f"Expense cannot be paid. Current status: {expense.status}")

    # 2. Finalize Status
    expense.status = ExpenseStatus.PAID
    # We could store reference_number and notes in the expense record if we added fields, 
    # but since we haven't added them to the model, we'll just log/commit for now.
    # If the user wants to store them, we'd need another model change.
    
    await db.commit()
    return {"status": "success", "message": "Expense marked as PAID"}

@router.get("/analytics/spend-by-category")
async def get_category_data(db: AsyncSession = Depends(get_db)):
    query = select(
        ExpenseRequest.category, 
        func.sum(ExpenseRequest.amount)
    ).where(ExpenseRequest.status == ExpenseStatus.PAID).group_by(ExpenseRequest.category)
    
    result = await db.execute(query)
    return {category: amount for category, amount in result.all()}


@router.get("/expenses/pending-payments", response_model=PaginatedExpenses)
async def get_pending_payments(
    page: int = 1,
    size: int = 25,
    search: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """Return paginated expenses that are approved but not yet paid."""
    # Role check
    if current_user.role != UserRole.ACCOUNTANT:
        raise HTTPException(status_code=403, detail="Access denied. Accountant role required.")

    # Query for expenses that are approved or auto-approved
    base_filters = [
        ExpenseRequest.org_id == current_user.org_id,
        ExpenseRequest.status.in_([ExpenseStatus.APPROVED, ExpenseStatus.AUTO_APPROVED])
    ]

    query = select(ExpenseRequest).options(
        selectinload(ExpenseRequest.requestor),
        selectinload(ExpenseRequest.approver),
        selectinload(ExpenseRequest.clarifications)
    ).where(*base_filters)

    if search:
        s = f"%{search}%"
        query = query.where(ExpenseRequest.request_id.ilike(s))

    # Get total count
    total_query = select(func.count(ExpenseRequest.id)).where(*base_filters)
    total = (await db.execute(total_query)).scalar() or 0

    # Get paginated results
    result = await db.execute(query.order_by(ExpenseRequest.created_at.desc()).limit(size).offset((page-1)*size))
    expenses = result.scalars().all()

    return {
        "total": total,
        "page": page,
        "size": size,
        "items": expenses
    }


@router.get("/expenses/paid", response_model=PaginatedExpenses)
async def get_paid_expenses(
    page: int = 1,
    size: int = 25,
    search: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """Return paginated expenses that have been marked as PAID."""
    # Role check
    if current_user.role != UserRole.ACCOUNTANT:
        raise HTTPException(status_code=403, detail="Access denied. Accountant role required.")

    base_filters = [
        ExpenseRequest.org_id == current_user.org_id,
        ExpenseRequest.status == ExpenseStatus.PAID
    ]

    query = select(ExpenseRequest).options(
        selectinload(ExpenseRequest.requestor),
        selectinload(ExpenseRequest.approver),
        selectinload(ExpenseRequest.clarifications)
    ).where(*base_filters)

    if search:
        s = f"%{search}%"
        query = query.where(ExpenseRequest.request_id.ilike(s))

    # Get total count
    total_query = select(func.count(ExpenseRequest.id)).where(*base_filters)
    total = (await db.execute(total_query)).scalar() or 0

    # Get paginated results — most recently paid first
    result = await db.execute(query.order_by(ExpenseRequest.updated_at.desc()).limit(size).offset((page-1)*size))
    expenses = result.scalars().all()

    return {
        "total": total,
        "page": page,
        "size": size,
        "items": expenses
    }



@router.post("/expenses/{expense_id}/mark-as-paid")
async def mark_expense_as_paid(
    expense_id: int,
    payload: Optional[MarkAsPaidRequest] = None,
    db: AsyncSession = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """Mark an approved expense as PAID manually (accountant only)."""

    # Role check
    if current_user.role != UserRole.ACCOUNTANT:
        raise HTTPException(status_code=403, detail="Only Accountants can mark expenses as paid.")

    # Fetch expense — must belong to the same org
    query = select(ExpenseRequest).where(
        ExpenseRequest.id == expense_id,
        ExpenseRequest.org_id == current_user.org_id
    )
    result = await db.execute(query)
    expense = result.scalar_one_or_none()

    if not expense:
        raise HTTPException(status_code=404, detail="Expense not found.")

    if expense.status not in [ExpenseStatus.APPROVED, ExpenseStatus.AUTO_APPROVED]:
        raise HTTPException(
            status_code=400,
            detail=f"Cannot mark as paid. Current status: {expense.status.value}"
        )

    # Update status and optional fields
    expense.status = ExpenseStatus.PAID
    if payload:
        if payload.payment_method:
            expense.payment_method = payload.payment_method.value  # store lowercase string value
        if payload.transaction_reference:
            expense.transaction_reference = payload.transaction_reference
        if payload.payment_note:
            expense.payment_note = payload.payment_note

    await db.commit()
    await db.refresh(expense)

    return {
        "status": "success",
        "message": "Expense marked as PAID successfully.",
        "expense_id": expense.id,
        "request_id": expense.request_id,
        "new_status": expense.status.value
    }
