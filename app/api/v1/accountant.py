from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy import func, extract
from sqlalchemy.orm import selectinload
from typing import Optional
import csv
import io
import datetime

from pydantic import BaseModel, Field
from app.db.session import get_db
from app.models.expense import ExpenseRequest, ExpenseStatus, PaymentMethod, ExpenseCategory
from app.models.notification import UserDeviceToken
from app.models.organization import Organization
from app.models.accounting import DailyBalance
from app.models.user import UserRole, User
from app.core.security import get_current_user
from app.core.config import settings
from app.core.utils import to_ist
from app.schemas.expense import PaginatedExpenses
from app.services.push_service import dispatch_push_notifications


class MarkAsPaidRequest(BaseModel):
    payment_method: Optional[PaymentMethod] = None
    transaction_reference: Optional[str] = None
    payment_note: Optional[str] = None

router = APIRouter(prefix="/accountant", tags=["accountant"])


@router.get("/payment-methods")
async def get_payment_methods(current_user = Depends(get_current_user)):
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


def _build_txn_row(t: "ExpenseRequest") -> dict:
    """Build a transaction row dict shared by dashboard, today-list, and detail endpoints."""
    requestor = t.requestor
    cat = t.category.value if hasattr(t.category, "value") else (t.category or "")
    return {
        "id": t.id,
        "request_id": t.request_id,
        "title": t.purpose or cat,
        "subtitle": (t.description or t.purpose or "")[:60],
        "icon_type": cat,
        "vendor_name": getattr(t, "vendor_name", None),
        "department": requestor.department.name if requestor and requestor.department else None,
        "timestamp": to_ist(t.paid_at or t.created_at),
        "amount": round(float(t.amount), 2),
        "status": t.status.value if hasattr(t.status, "value") else t.status,
        "requestor_name": f"{requestor.first_name} {requestor.last_name}".strip() if requestor else "",
    }


@router.get("/dashboard")
async def get_financial_summary(
    db: AsyncSession = Depends(get_db),
    current_user = Depends(get_current_user)
):
    if current_user.role != UserRole.ACCOUNTANT:
        raise HTTPException(status_code=403, detail="Access denied. Accountant role required.")

    today = datetime.date.today()

    # Today's DailyBalance row
    bal_result = await db.execute(
        select(DailyBalance).where(
            DailyBalance.org_id == current_user.org_id,
            DailyBalance.balance_date == today,
        )
    )
    bal = bal_result.scalar_one_or_none()

    # Fallback: use org's opening_balance if no daily row exists
    org_result = await db.execute(select(Organization).where(Organization.id == current_user.org_id))
    org = org_result.scalar_one_or_none()
    opening = float(bal.opening_balance if bal else (org.opening_balance if org else 0.0))
    amount_in = float(bal.amount_in if bal else 0.0)

    # Amount out = sum of PAID expenses today
    amount_out_q = select(func.coalesce(func.sum(ExpenseRequest.amount), 0.0)).where(
        ExpenseRequest.org_id == current_user.org_id,
        ExpenseRequest.status == ExpenseStatus.PAID,
        func.date(func.coalesce(ExpenseRequest.paid_at, ExpenseRequest.updated_at)) == today,
    )
    amount_out = float((await db.execute(amount_out_q)).scalar())

    closing = round(opening + amount_in - amount_out, 2)

    # Pending payments count
    pending_q = select(func.count(ExpenseRequest.id)).where(
        ExpenseRequest.org_id == current_user.org_id,
        ExpenseRequest.status.in_([ExpenseStatus.APPROVED, ExpenseStatus.AUTO_APPROVED]),
    )
    pending_count = int((await db.execute(pending_q)).scalar() or 0)

    # Today's transactions (up to 10, with requestor + department)
    today_txn_q = (
        select(ExpenseRequest)
        .options(selectinload(ExpenseRequest.requestor).selectinload(User.department))
        .where(
            ExpenseRequest.org_id == current_user.org_id,
            ExpenseRequest.status == ExpenseStatus.PAID,
            func.date(func.coalesce(ExpenseRequest.paid_at, ExpenseRequest.updated_at)) == today,
        )
        .order_by(ExpenseRequest.paid_at.desc())
        .limit(10)
    )
    today_txns = (await db.execute(today_txn_q)).scalars().all()

    return {
        "user": {"shortName": current_user.first_name},
        "accountOverview": {
            "openBalance": round(opening, 2),
            "closingBalance": closing,
            "amountIn": round(amount_in, 2),
            "amountOut": round(amount_out, 2),
            "inHandCash": closing,
            "inHandCashGrowth": "+0.0%",
        },
        "tasksSummary": {
            "pendingPaymentsCount": pending_count,
        },
        "todayTransactions": [_build_txn_row(t) for t in today_txns],
    }

@router.get("/transactions/today")
async def get_today_transactions(
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Full list of today's paid transactions (View All screen)."""
    if current_user.role != UserRole.ACCOUNTANT:
        raise HTTPException(status_code=403, detail="Access denied. Accountant role required.")

    from datetime import timezone, timedelta
    _IST = timezone(timedelta(hours=5, minutes=30))
    today_ist = datetime.datetime.now(_IST).date()

    result = await db.execute(
        select(ExpenseRequest)
        .options(selectinload(ExpenseRequest.requestor).selectinload(User.department))
        .where(
            ExpenseRequest.org_id == current_user.org_id,
            ExpenseRequest.status == ExpenseStatus.PAID,
            func.date(func.coalesce(ExpenseRequest.paid_at, ExpenseRequest.updated_at)) == today_ist,
        )
        .order_by(ExpenseRequest.paid_at.desc())
    )
    transactions = result.scalars().all()
    rows = [_build_txn_row(t) for t in transactions]
    total_out = sum(r["amount"] for r in rows)

    return {
        "date": str(today_ist),
        "total_in": 0.0,
        "total_out": round(total_out, 2),
        "net": round(-total_out, 2),
        "count": len(rows),
        "transactions": rows,
    }


@router.get("/transactions/{transaction_id}")
async def get_transaction_detail(
    transaction_id: str,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Detail view for a single transaction. Accepts numeric DB id or EXP-XXXXXXXX string."""
    if current_user.role != UserRole.ACCOUNTANT:
        raise HTTPException(status_code=403, detail="Access denied. Accountant role required.")

    filter_clause = (
        ExpenseRequest.id == int(transaction_id)
        if transaction_id.isdigit()
        else ExpenseRequest.request_id == transaction_id
    )
    result = await db.execute(
        select(ExpenseRequest)
        .options(
            selectinload(ExpenseRequest.requestor).selectinload(User.department),
            selectinload(ExpenseRequest.approver),
        )
        .where(filter_clause, ExpenseRequest.org_id == current_user.org_id)
    )
    e = result.scalar_one_or_none()
    if not e:
        raise HTTPException(status_code=404, detail="Transaction not found.")

    requestor = e.requestor
    audit_trail = []
    if requestor and e.created_at:
        audit_trail.append({
            "label": "Submitted",
            "actor": f"{requestor.first_name} {requestor.last_name}".strip(),
            "actor_role": "requestor",
            "timestamp": to_ist(e.created_at),
            "note": None,
        })
    if e.approver and e.approved_at:
        audit_trail.append({
            "label": "Approved",
            "actor": f"{e.approver.first_name} {e.approver.last_name}".strip(),
            "actor_role": "approver",
            "timestamp": to_ist(e.approved_at),
            "note": None,
        })
    if e.status == ExpenseStatus.PAID and e.paid_at:
        audit_trail.append({
            "label": "Paid",
            "actor": "Accountant",
            "actor_role": "accountant",
            "timestamp": to_ist(e.paid_at),
            "note": e.payment_note,
        })

    cat = e.category.value if hasattr(e.category, "value") else (e.category or "")
    return {
        "id": e.id,
        "request_id": e.request_id,
        "amount": round(float(e.amount), 2),
        "purpose": e.purpose,
        "description": e.description,
        "category": cat,
        "department": requestor.department.name if requestor and requestor.department else None,
        "status": e.status.value if hasattr(e.status, "value") else e.status,
        "payment_status": "paid" if e.status == ExpenseStatus.PAID else "pending",
        "created_at": to_ist(e.created_at),
        "approved_at": to_ist(e.approved_at),
        "rejected_at": to_ist(e.rejected_at),
        "paid_at": to_ist(e.paid_at),
        "requestor": {
            "first_name": requestor.first_name if requestor else "",
            "last_name": requestor.last_name if requestor else "",
            "email": requestor.email if requestor else "",
        },
        "requestor_name": f"{requestor.first_name} {requestor.last_name}".strip() if requestor else "",
        "requestor_email": requestor.email if requestor else "",
        "vendor_name": getattr(e, "vendor_name", None),
        "payment_method": e.payment_method,
        "transaction_reference": e.transaction_reference,
        "receipt_url": e.receipt_url,
        "payment_qr_url": e.payment_qr_url,
        "audit_trail": audit_trail,
    }


class ProcessPayoutRequest(BaseModel):
    expense_id: int
    reference_number: Optional[str] = None
    accountant_note: Optional[str] = None


@router.post("/process-payout")
async def process_payout(
    payload: ProcessPayoutRequest,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """Mark an expense as PAID manually."""
    # 0. Role Check
    if current_user.role != UserRole.ACCOUNTANT:
        raise HTTPException(status_code=403, detail="Only Accountants can process payouts.")

    # 1. Verify Expense is in APPROVED/AUTO_APPROVED state
    query = select(ExpenseRequest).where(
        ExpenseRequest.id == payload.expense_id,
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
    expense.paid_at = datetime.datetime.utcnow()
    if payload.reference_number:
        expense.transaction_reference = payload.reference_number
    if payload.accountant_note:
        expense.payment_note = payload.accountant_note

    await db.commit()

    # Push notification to requestor
    token_result = await db.execute(
        select(UserDeviceToken.token).where(
            UserDeviceToken.user_id == expense.user_id,
            UserDeviceToken.is_active.is_(True),
        )
    )
    requestor_tokens = [r[0] for r in token_result.all()]
    if requestor_tokens:
        background_tasks.add_task(
            dispatch_push_notifications,
            tokens=requestor_tokens,
            title="Payment Processed 💸",
            body=f"Your ₹{round(float(expense.amount), 0):,.0f} expense for {expense.purpose} has been paid.",
            data={
                "event_type": "expense_paid",
                "expense_id": str(expense.id),
                "request_id": expense.request_id,
                "status": "paid",
            },
        )

    return {"status": "success", "message": "Expense marked as PAID"}

@router.get("/analytics/spend-by-category")
async def get_category_data(
    db: AsyncSession = Depends(get_db),
    current_user = Depends(get_current_user)
):
    if current_user.role != UserRole.ACCOUNTANT:
        raise HTTPException(status_code=403, detail="Access denied. Accountant role required.")
    query = select(
        ExpenseRequest.category, 
        func.sum(ExpenseRequest.amount)
    ).where(ExpenseRequest.status == ExpenseStatus.PAID).group_by(ExpenseRequest.category)
    
    result = await db.execute(query)
    return {category: amount for category, amount in result.all()}


@router.get("/expenses/pending-payments")
async def get_pending_payments(
    page: int = 1,
    size: int = 25,
    search: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """Return paginated expenses that are approved but not yet paid."""
    if current_user.role != UserRole.ACCOUNTANT:
        raise HTTPException(status_code=403, detail="Access denied. Accountant role required.")

    base_filters = [
        ExpenseRequest.org_id == current_user.org_id,
        ExpenseRequest.status.in_([ExpenseStatus.APPROVED, ExpenseStatus.AUTO_APPROVED])
    ]

    query = select(ExpenseRequest).options(
        selectinload(ExpenseRequest.requestor).selectinload(User.department),
        selectinload(ExpenseRequest.approver),
        selectinload(ExpenseRequest.clarifications)
    ).where(*base_filters)

    if search:
        s = f"%{search}%"
        query = query.where(ExpenseRequest.request_id.ilike(s))

    total_query = select(func.count(ExpenseRequest.id)).where(*base_filters)
    total = (await db.execute(total_query)).scalar() or 0

    result = await db.execute(query.order_by(ExpenseRequest.created_at.desc()).limit(size).offset((page-1)*size))
    expenses = result.scalars().all()

    return {
        "total": total,
        "page": page,
        "size": size,
        "items": [
            {
                "id": e.id,
                "request_id": e.request_id,
                "amount": round(float(e.amount), 2),
                "purpose": e.purpose,
                "description": e.description,
                "category": e.category.value if hasattr(e.category, "value") else e.category,
                "department": e.requestor.department.name if e.requestor and e.requestor.department else None,
                "status": e.status.value if hasattr(e.status, "value") else e.status,
                "payment_status": "pending",
                "receipt_url": e.receipt_url,
                "payment_qr_url": e.payment_qr_url,
                "payment_method": e.payment_method,
                "transaction_reference": e.transaction_reference,
                "requestor": {
                    "first_name": e.requestor.first_name if e.requestor else "",
                    "last_name": e.requestor.last_name if e.requestor else "",
                    "email": e.requestor.email if e.requestor else "",
                },
                "requestor_name": f"{e.requestor.first_name} {e.requestor.last_name}".strip() if e.requestor else "",
                "created_at": to_ist(e.created_at),
                "approved_at": to_ist(e.approved_at),
            }
            for e in expenses
        ],
    }


@router.get("/expenses/paid")
async def get_paid_expenses(
    page: int = 1,
    size: int = 25,
    search: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """Return paginated expenses that have been marked as PAID."""
    if current_user.role != UserRole.ACCOUNTANT:
        raise HTTPException(status_code=403, detail="Access denied. Accountant role required.")

    base_filters = [
        ExpenseRequest.org_id == current_user.org_id,
        ExpenseRequest.status == ExpenseStatus.PAID
    ]

    query = select(ExpenseRequest).options(
        selectinload(ExpenseRequest.requestor).selectinload(User.department),
        selectinload(ExpenseRequest.approver),
        selectinload(ExpenseRequest.clarifications)
    ).where(*base_filters)

    if search:
        s = f"%{search}%"
        query = query.where(ExpenseRequest.request_id.ilike(s))

    total_query = select(func.count(ExpenseRequest.id)).where(*base_filters)
    total = (await db.execute(total_query)).scalar() or 0

    result = await db.execute(query.order_by(ExpenseRequest.updated_at.desc()).limit(size).offset((page-1)*size))
    expenses = result.scalars().all()

    return {
        "total": total,
        "page": page,
        "size": size,
        "items": [
            {
                "id": e.id,
                "request_id": e.request_id,
                "amount": round(float(e.amount), 2),
                "purpose": e.purpose,
                "description": e.description,
                "category": e.category.value if hasattr(e.category, "value") else e.category,
                "department": e.requestor.department.name if e.requestor and e.requestor.department else None,
                "status": e.status.value if hasattr(e.status, "value") else e.status,
                "payment_status": "paid",
                "receipt_url": e.receipt_url,
                "payment_qr_url": e.payment_qr_url,
                "payment_method": e.payment_method,
                "transaction_reference": e.transaction_reference,
                "requestor": {
                    "first_name": e.requestor.first_name if e.requestor else "",
                    "last_name": e.requestor.last_name if e.requestor else "",
                    "email": e.requestor.email if e.requestor else "",
                },
                "requestor_name": f"{e.requestor.first_name} {e.requestor.last_name}".strip() if e.requestor else "",
                "created_at": to_ist(e.created_at),
                "approved_at": to_ist(e.approved_at),
                "paid_at": to_ist(e.paid_at or e.updated_at),
                "audit_trail": [
                    {"action": "submitted", "actor": f"{e.requestor.first_name} {e.requestor.last_name}".strip() if e.requestor else "", "at": to_ist(e.created_at), "note": None},
                    *([{"action": "approved", "actor": f"{e.approver.first_name} {e.approver.last_name}".strip(), "at": to_ist(e.approved_at), "note": None}] if e.approver and e.approved_at else []),
                    *([{"action": "paid", "actor": "Accountant", "at": to_ist(e.paid_at or e.updated_at), "note": e.payment_note}] if e.status == ExpenseStatus.PAID else []),
                ],
            }
            for e in expenses
        ],
    }


@router.post("/expenses/{expense_id}/mark-as-paid")
async def mark_expense_as_paid(
    expense_id: int,
    background_tasks: BackgroundTasks,
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
    expense.paid_at = datetime.datetime.utcnow()
    if payload:
        if payload.payment_method:
            expense.payment_method = payload.payment_method.value  # store lowercase string value
        if payload.transaction_reference:
            expense.transaction_reference = payload.transaction_reference
        if payload.payment_note:
            expense.payment_note = payload.payment_note

    await db.commit()
    await db.refresh(expense)

    # Push notification to requestor
    token_result = await db.execute(
        select(UserDeviceToken.token).where(
            UserDeviceToken.user_id == expense.user_id,
            UserDeviceToken.is_active.is_(True),
        )
    )
    requestor_tokens = [r[0] for r in token_result.all()]
    if requestor_tokens:
        background_tasks.add_task(
            dispatch_push_notifications,
            tokens=requestor_tokens,
            title="Payment Processed 💸",
            body=f"Your ₹{round(float(expense.amount), 0):,.0f} expense for {expense.purpose} has been paid.",
            data={
                "event_type": "expense_paid",
                "expense_id": str(expense.id),
                "request_id": expense.request_id,
                "status": "paid",
            },
        )

    return {
        "status": "success",
        "message": "Expense marked as PAID successfully.",
        "expense_id": expense.id,
        "request_id": expense.request_id,
        "new_status": expense.status.value
    }


# ─────────────────────────────────────────────────────────────────────────────
# Opening Balance
# ─────────────────────────────────────────────────────────────────────────────

class BalanceRequest(BaseModel):
    openingBalance: float = Field(..., ge=0, description="Opening cash balance (>= 0)")
    closingBalance: Optional[float] = None
    note: Optional[str] = None
    date: Optional[str] = None  # YYYY-MM-DD, defaults to today


def _balance_response(bal: DailyBalance, amount_out: float, updater: User | None) -> dict:
    opening = bal.opening_balance
    amount_in = bal.amount_in
    closing = round(opening + amount_in - amount_out, 2)
    return {
        "date": bal.balance_date.isoformat(),
        "opening_balance": round(opening, 2),
        "closing_balance": closing,
        "amount_in": round(amount_in, 2),
        "amount_out": round(amount_out, 2),
        "last_updated_at": to_ist(bal.updated_at),
        "note": bal.note,
        "updated_by": f"{updater.first_name} {updater.last_name}".strip() if updater else None,
    }


@router.get("/balance")
async def get_balance(
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Return today's balance snapshot for the org."""
    if current_user.role != UserRole.ACCOUNTANT:
        raise HTTPException(status_code=403, detail="Access denied. Accountant role required.")

    today = datetime.date.today()
    bal_result = await db.execute(
        select(DailyBalance).options(selectinload(DailyBalance.updated_by)).where(
            DailyBalance.org_id == current_user.org_id,
            DailyBalance.balance_date == today,
        )
    )
    bal = bal_result.scalar_one_or_none()

    amount_out_q = select(func.coalesce(func.sum(ExpenseRequest.amount), 0.0)).where(
        ExpenseRequest.org_id == current_user.org_id,
        ExpenseRequest.status == ExpenseStatus.PAID,
        func.date(func.coalesce(ExpenseRequest.paid_at, ExpenseRequest.updated_at)) == today,
    )
    amount_out = float((await db.execute(amount_out_q)).scalar())

    if bal:
        return _balance_response(bal, amount_out, bal.updated_by)

    # No row yet — return org's opening balance as default
    org_result = await db.execute(select(Organization).where(Organization.id == current_user.org_id))
    org = org_result.scalar_one_or_none()
    opening = float(org.opening_balance if org else 0.0)
    return {
        "date": today.isoformat(),
        "opening_balance": round(opening, 2),
        "closing_balance": round(opening - amount_out, 2),
        "amount_in": 0.0,
        "amount_out": round(amount_out, 2),
        "last_updated_at": None,
        "note": None,
        "updated_by": None,
    }


@router.get("/balance/history")
async def get_balance_history(
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Return past daily balance snapshots for the org, newest first."""
    if current_user.role != UserRole.ACCOUNTANT:
        raise HTTPException(status_code=403, detail="Access denied. Accountant role required.")

    result = await db.execute(
        select(DailyBalance).options(selectinload(DailyBalance.updated_by)).where(
            DailyBalance.org_id == current_user.org_id
        ).order_by(DailyBalance.balance_date.desc())
    )
    rows = result.scalars().all()

    # For each row, compute amount_out for that day
    history = []
    for row in rows:
        ao_q = select(func.coalesce(func.sum(ExpenseRequest.amount), 0.0)).where(
            ExpenseRequest.org_id == current_user.org_id,
            ExpenseRequest.status == ExpenseStatus.PAID,
            func.date(func.coalesce(ExpenseRequest.paid_at, ExpenseRequest.updated_at)) == row.balance_date,
        )
        amount_out = float((await db.execute(ao_q)).scalar())
        history.append(_balance_response(row, amount_out, row.updated_by))

    return history


@router.post("/balance")
async def set_opening_balance(
    payload: BalanceRequest,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Set / update the opening balance for a given date (default: today)."""
    if current_user.role != UserRole.ACCOUNTANT:
        raise HTTPException(status_code=403, detail="Access denied. Accountant role required.")

    balance_date = datetime.date.today()
    if payload.date:
        try:
            balance_date = datetime.date.fromisoformat(payload.date)
        except ValueError:
            raise HTTPException(status_code=400, detail="date must be YYYY-MM-DD")

    # Upsert DailyBalance
    bal_result = await db.execute(
        select(DailyBalance).where(
            DailyBalance.org_id == current_user.org_id,
            DailyBalance.balance_date == balance_date,
        )
    )
    bal = bal_result.scalar_one_or_none()
    if bal:
        bal.opening_balance = payload.openingBalance
        if payload.note is not None:
            bal.note = payload.note
        bal.updated_by_user_id = current_user.id
    else:
        bal = DailyBalance(
            org_id=current_user.org_id,
            balance_date=balance_date,
            opening_balance=payload.openingBalance,
            amount_in=0.0,
            note=payload.note,
            updated_by_user_id=current_user.id,
        )
        db.add(bal)

    # Also sync org-level opening_balance for backward compat
    org_result = await db.execute(select(Organization).where(Organization.id == current_user.org_id))
    org = org_result.scalar_one_or_none()
    if org:
        org.opening_balance = payload.openingBalance

    await db.commit()
    await db.refresh(bal)

    # Compute amount_out for that date
    ao_q = select(func.coalesce(func.sum(ExpenseRequest.amount), 0.0)).where(
        ExpenseRequest.org_id == current_user.org_id,
        ExpenseRequest.status == ExpenseStatus.PAID,
        func.date(func.coalesce(ExpenseRequest.paid_at, ExpenseRequest.updated_at)) == balance_date,
    )
    amount_out = float((await db.execute(ao_q)).scalar())

    updater_result = await db.execute(select(User).where(User.id == bal.updated_by_user_id))
    updater = updater_result.scalar_one_or_none()

    return _balance_response(bal, amount_out, updater)


# ─────────────────────────────────────────────────────────────────────────────
# Payment status for a single expense
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/expenses/{expense_id}/payment-status")
async def get_expense_payment_status(
    expense_id: int,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Return the payment status for a specific expense."""
    if current_user.role != UserRole.ACCOUNTANT:
        raise HTTPException(status_code=403, detail="Access denied. Accountant role required.")

    result = await db.execute(
        select(ExpenseRequest).where(
            ExpenseRequest.id == expense_id,
            ExpenseRequest.org_id == current_user.org_id,
        )
    )
    expense = result.scalar_one_or_none()
    if not expense:
        raise HTTPException(status_code=404, detail="Expense not found.")

    paid_at = expense.updated_at if expense.status == ExpenseStatus.PAID else None

    return {
        "expense_id": expense.id,
        "request_id": expense.request_id,
        "status": expense.status.value,
        "payment_method": expense.payment_method,
        "transaction_reference": expense.transaction_reference,
        "paid_at": paid_at.isoformat() if paid_at else None,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Reports — Summary
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/reports/summary")
async def get_reports_summary(
    month: Optional[int] = None,
    year: Optional[int] = None,
    category: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """
    Return a summary of expenses for the given period.
    All three query params are optional; omitting them returns the all-time summary.
    """
    if current_user.role != UserRole.ACCOUNTANT:
        raise HTTPException(status_code=403, detail="Access denied. Accountant role required.")

    base_filters = [ExpenseRequest.org_id == current_user.org_id]

    if year:
        base_filters.append(extract("year", ExpenseRequest.created_at) == year)
    if month:
        base_filters.append(extract("month", ExpenseRequest.created_at) == month)
    if category:
        try:
            cat = ExpenseCategory(category.lower())
            base_filters.append(ExpenseRequest.category == cat)
        except ValueError:
            raise HTTPException(status_code=400, detail=f"Unknown category: {category}")

    # Total + count
    total_q = select(
        func.coalesce(func.sum(ExpenseRequest.amount), 0.0),
        func.count(ExpenseRequest.id),
    ).where(*base_filters)
    total_result = await db.execute(total_q)
    total_amount, count = total_result.one()

    # By category
    cat_q = select(
        ExpenseRequest.category,
        func.coalesce(func.sum(ExpenseRequest.amount), 0.0),
    ).where(*base_filters).group_by(ExpenseRequest.category)
    cat_result = await db.execute(cat_q)
    by_category = {row[0].value: round(float(row[1]), 2) for row in cat_result.all()}

    # By status
    status_q = select(
        ExpenseRequest.status,
        func.coalesce(func.sum(ExpenseRequest.amount), 0.0),
    ).where(*base_filters).group_by(ExpenseRequest.status)
    status_result = await db.execute(status_q)
    by_status = {row[0].value: round(float(row[1]), 2) for row in status_result.all()}

    return {
        "total_amount": round(float(total_amount), 2),
        "count": count,
        "by_category": by_category,
        "by_status": by_status,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Analytics — Spend (replaces/coexists with /analytics/spend-by-category)
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/analytics/spend")
async def get_spend_analytics(
    time_range: Optional[str] = None,
    department: Optional[str] = None,
    category: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """
    Flexible analytics endpoint.
    time_range: '30d', '90d', '180d', '1y' — defaults to all-time.
    department: department name filter.
    category: ExpenseCategory value filter.
    """
    if current_user.role != UserRole.ACCOUNTANT:
        raise HTTPException(status_code=403, detail="Access denied. Accountant role required.")

    from app.models.user import User as UserModel
    from app.models.department import Department

    base_filters = [ExpenseRequest.org_id == current_user.org_id]

    # Time range filter
    if time_range:
        days_map = {"30d": 30, "90d": 90, "180d": 180, "1y": 365}
        days = days_map.get(time_range.lower())
        if not days:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid time_range '{time_range}'. Valid: 30d, 90d, 180d, 1y",
            )
        cutoff = datetime.datetime.utcnow() - datetime.timedelta(days=days)
        base_filters.append(ExpenseRequest.created_at >= cutoff)

    # Category filter
    if category:
        try:
            cat = ExpenseCategory(category.lower())
            base_filters.append(ExpenseRequest.category == cat)
        except ValueError:
            raise HTTPException(status_code=400, detail=f"Unknown category: {category}")

    # Department filter (join through requestor → user.department_id)
    if department:
        dep_result = await db.execute(
            select(Department).where(
                Department.org_id == current_user.org_id,
                func.lower(Department.name) == department.lower(),
            )
        )
        dep = dep_result.scalar_one_or_none()
        if not dep:
            raise HTTPException(status_code=404, detail=f"Department '{department}' not found.")
        base_filters.append(
            ExpenseRequest.user_id.in_(
                select(UserModel.id).where(UserModel.department_id == dep.id)
            )
        )

    # Total
    total_q = select(func.coalesce(func.sum(ExpenseRequest.amount), 0.0)).where(*base_filters)
    total = float((await db.execute(total_q)).scalar())

    # By category
    cat_q = select(
        ExpenseRequest.category,
        func.coalesce(func.sum(ExpenseRequest.amount), 0.0),
    ).where(*base_filters).group_by(ExpenseRequest.category)
    cat_rows = (await db.execute(cat_q)).all()
    by_category = {row[0].value: round(float(row[1]), 2) for row in cat_rows}

    # By period (monthly breakdown)
    period_q = select(
        extract("year", ExpenseRequest.created_at).label("yr"),
        extract("month", ExpenseRequest.created_at).label("mo"),
        func.coalesce(func.sum(ExpenseRequest.amount), 0.0).label("total"),
    ).where(*base_filters).group_by("yr", "mo").order_by("yr", "mo")
    period_rows = (await db.execute(period_q)).all()
    by_period = [
        {"year": int(r.yr), "month": int(r.mo), "total": round(float(r.total), 2)}
        for r in period_rows
    ]

    # By department (all departments in org, regardless of filter)
    dept_q = select(
        Department.name,
        func.coalesce(func.sum(ExpenseRequest.amount), 0.0),
    ).join(
        UserModel, UserModel.department_id == Department.id
    ).join(
        ExpenseRequest, ExpenseRequest.user_id == UserModel.id
    ).where(
        Department.org_id == current_user.org_id,
        *([base_filters[0]] + [f for f in base_filters[1:] if "department_id" not in str(f)]),
    ).group_by(Department.name)
    dept_rows = (await db.execute(dept_q)).all()
    by_department = [
        {"department": row[0], "total": round(float(row[1]), 2)} for row in dept_rows
    ]

    return {
        "total": round(total, 2),
        "by_period": by_period,
        "by_department": by_department,
        "by_category": by_category,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Export — CSV
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/reports/export/csv")
async def export_expenses_csv(
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    category: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """
    Export approved/paid expenses as a CSV file.
    Optional params: start_date (YYYY-MM-DD), end_date (YYYY-MM-DD), category.
    """
    if current_user.role != UserRole.ACCOUNTANT:
        raise HTTPException(status_code=403, detail="Access denied. Accountant role required.")

    base_filters = [
        ExpenseRequest.org_id == current_user.org_id,
        ExpenseRequest.status.in_([ExpenseStatus.APPROVED, ExpenseStatus.AUTO_APPROVED, ExpenseStatus.PAID]),
    ]

    if start_date:
        try:
            sd = datetime.datetime.strptime(start_date, "%Y-%m-%d")
            base_filters.append(ExpenseRequest.created_at >= sd)
        except ValueError:
            raise HTTPException(status_code=400, detail="start_date must be YYYY-MM-DD")
    if end_date:
        try:
            ed = datetime.datetime.strptime(end_date, "%Y-%m-%d") + datetime.timedelta(days=1)
            base_filters.append(ExpenseRequest.created_at < ed)
        except ValueError:
            raise HTTPException(status_code=400, detail="end_date must be YYYY-MM-DD")
    if category:
        try:
            cat = ExpenseCategory(category.lower())
            base_filters.append(ExpenseRequest.category == cat)
        except ValueError:
            raise HTTPException(status_code=400, detail=f"Unknown category: {category}")

    result = await db.execute(
        select(ExpenseRequest)
        .options(selectinload(ExpenseRequest.requestor))
        .where(*base_filters)
        .order_by(ExpenseRequest.created_at.desc())
    )
    expenses = result.scalars().all()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "Request ID", "Purpose", "Category", "Amount", "Status",
        "Request Type", "Requestor", "Payment Method", "Transaction Reference",
        "Created At", "Updated At",
    ])
    for e in expenses:
        requestor_name = (
            f"{e.requestor.first_name} {e.requestor.last_name}" if e.requestor else ""
        )
        writer.writerow([
            e.request_id,
            e.purpose,
            e.category.value,
            round(float(e.amount), 2),
            e.status.value,
            e.request_type.value,
            requestor_name,
            e.payment_method or "",
            e.transaction_reference or "",
            e.created_at.strftime("%Y-%m-%d %H:%M:%S") if e.created_at else "",
            e.updated_at.strftime("%Y-%m-%d %H:%M:%S") if e.updated_at else "",
        ])

    output.seek(0)
    filename = f"expenses_{datetime.datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.csv"
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


# ─────────────────────────────────────────────────────────────────────────────
# Export — PDF
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/reports/export/pdf")
async def export_expenses_pdf(
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    category: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """
    Export approved/paid expenses as a PDF file (generated with reportlab).
    Optional params: start_date (YYYY-MM-DD), end_date (YYYY-MM-DD), category.
    """
    if current_user.role != UserRole.ACCOUNTANT:
        raise HTTPException(status_code=403, detail="Access denied. Accountant role required.")

    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.lib.units import cm
    from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer

    base_filters = [
        ExpenseRequest.org_id == current_user.org_id,
        ExpenseRequest.status.in_([ExpenseStatus.APPROVED, ExpenseStatus.AUTO_APPROVED, ExpenseStatus.PAID]),
    ]

    if start_date:
        try:
            sd = datetime.datetime.strptime(start_date, "%Y-%m-%d")
            base_filters.append(ExpenseRequest.created_at >= sd)
        except ValueError:
            raise HTTPException(status_code=400, detail="start_date must be YYYY-MM-DD")
    if end_date:
        try:
            ed = datetime.datetime.strptime(end_date, "%Y-%m-%d") + datetime.timedelta(days=1)
            base_filters.append(ExpenseRequest.created_at < ed)
        except ValueError:
            raise HTTPException(status_code=400, detail="end_date must be YYYY-MM-DD")
    if category:
        try:
            cat = ExpenseCategory(category.lower())
            base_filters.append(ExpenseRequest.category == cat)
        except ValueError:
            raise HTTPException(status_code=400, detail=f"Unknown category: {category}")

    result = await db.execute(
        select(ExpenseRequest)
        .options(selectinload(ExpenseRequest.requestor))
        .where(*base_filters)
        .order_by(ExpenseRequest.created_at.desc())
    )
    expenses = result.scalars().all()

    # Build PDF in memory
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=landscape(A4), leftMargin=1 * cm, rightMargin=1 * cm)
    styles = getSampleStyleSheet()
    elements = []

    elements.append(Paragraph("Expense Report", styles["Title"]))
    elements.append(Paragraph(
        f"Generated: {datetime.datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}",
        styles["Normal"],
    ))
    elements.append(Spacer(1, 0.5 * cm))

    headers = ["Request ID", "Purpose", "Category", "Amount (₹)", "Status", "Requestor", "Created At"]
    data = [headers]
    for e in expenses:
        requestor_name = (
            f"{e.requestor.first_name} {e.requestor.last_name}" if e.requestor else "-"
        )
        data.append([
            e.request_id,
            e.purpose[:40] + ("…" if len(e.purpose) > 40 else ""),
            e.category.value,
            f"{round(float(e.amount), 2):,.2f}",
            e.status.value,
            requestor_name,
            e.created_at.strftime("%Y-%m-%d") if e.created_at else "",
        ])

    col_widths = [3 * cm, 6 * cm, 3 * cm, 3 * cm, 3 * cm, 4 * cm, 3 * cm]
    table = Table(data, colWidths=col_widths, repeatRows=1)
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1a56db")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f3f4f6")]),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#d1d5db")),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    elements.append(table)

    doc.build(elements)
    buffer.seek(0)

    filename = f"expenses_{datetime.datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.pdf"
    return StreamingResponse(
        iter([buffer.read()]),
        media_type="application/pdf",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )
