from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy.orm import selectinload
from sqlalchemy import func
from typing import Optional

from app.db.session import get_db
from app.models.expense import ExpenseRequest, ExpenseStatus
from app.models.user import UserRole, User
from app.models.department import Department
from app.core.security import get_current_user
from app.core.roles import enforce_branch_scope, is_admin_like
from app.core.utils import to_ist


router = APIRouter(prefix="/admin", tags=["admin"])


def _status_for_admin_history(status: ExpenseStatus) -> str:
    if status == ExpenseStatus.APPROVED:
        return "approved"
    if status == ExpenseStatus.AUTO_APPROVED:
        return "auto_approved"
    if status == ExpenseStatus.REJECTED:
        return "rejected"
    if status in [ExpenseStatus.CLARIFICATION_REQUIRED, ExpenseStatus.CLARIFICATION_RESPONDED]:
        return "clarification"
    return "pending"


@router.get("/dashboard")
async def get_admin_dashboard(
    branch_id: int | None = None,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    if not is_admin_like(current_user):
        raise HTTPException(status_code=403, detail="Access denied. Admin role required.")

    effective_branch_id = enforce_branch_scope(current_user, branch_id)
    branch_user_filter = []
    if effective_branch_id is not None:
        branch_user_filter.append(ExpenseRequest.user_id.in_(select(User.id).where(User.branch_id == effective_branch_id)))

    pending_query = select(func.count(ExpenseRequest.id)).where(
        ExpenseRequest.org_id == current_user.org_id,
        ExpenseRequest.status.in_([ExpenseStatus.PENDING, ExpenseStatus.CLARIFICATION_RESPONDED]),
        *branch_user_filter,
    )
    pending_requests = int((await db.execute(pending_query)).scalar() or 0)

    clarification_query = select(func.count(ExpenseRequest.id)).where(
        ExpenseRequest.org_id == current_user.org_id,
        ExpenseRequest.status == ExpenseStatus.CLARIFICATION_REQUIRED,
        *branch_user_filter,
    )
    clarification_pending = int((await db.execute(clarification_query)).scalar() or 0)

    approved_amount_query = select(func.sum(ExpenseRequest.amount)).where(
        ExpenseRequest.org_id == current_user.org_id,
        ExpenseRequest.status.in_([ExpenseStatus.APPROVED, ExpenseStatus.AUTO_APPROVED, ExpenseStatus.PAID]),
        *branch_user_filter,
    )
    approved_amount = float((await db.execute(approved_amount_query)).scalar() or 0)

    total_departments_query = select(func.count(Department.id)).where(
        Department.org_id == current_user.org_id,
    )
    total_departments = int((await db.execute(total_departments_query)).scalar() or 0)

    active_departments_query = select(func.count(Department.id)).where(
        Department.org_id == current_user.org_id,
        Department.is_active == True,
    )
    active_departments = int((await db.execute(active_departments_query)).scalar() or 0)

    unassigned_users_query = select(func.count(User.id)).where(
        User.org_id == current_user.org_id,
        User.is_active == True,
        User.department_id == None,
    )
    if effective_branch_id is not None:
        unassigned_users_query = unassigned_users_query.where(User.branch_id == effective_branch_id)
    unassigned_users = int((await db.execute(unassigned_users_query)).scalar() or 0)

    return {
        "user": {
            "shortName": current_user.first_name,
        },
        "overview": {
            "pendingRequestsCount": pending_requests,
            "inClarificationCount": clarification_pending,
            "approvedAmount": round(approved_amount, 2),
        },
        "departmentSummary": {
            "totalDepartments": total_departments,
            "activeDepartments": active_departments,
            "unassignedUsers": unassigned_users,
        },
    }


@router.get("/history")
async def get_admin_history(
    search: Optional[str] = None,
    status: Optional[str] = "All",
    branch_id: int | None = None,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    if not is_admin_like(current_user):
        raise HTTPException(status_code=403, detail="Access denied. Admin role required.")

    effective_branch_id = enforce_branch_scope(current_user, branch_id)

    query = select(ExpenseRequest).options(
        selectinload(ExpenseRequest.requestor).selectinload(User.department),
        selectinload(ExpenseRequest.clarifications),
    ).where(
        ExpenseRequest.org_id == current_user.org_id
    )
    if effective_branch_id is not None:
        query = query.where(
            ExpenseRequest.user_id.in_(
                select(User.id).where(User.branch_id == effective_branch_id)
            )
        )

    selected_status = (status or "All").strip().lower()
    if selected_status not in ["all", "approved", "auto_approved", "rejected", "clarification"]:
        raise HTTPException(status_code=400, detail="Invalid status filter")

    if selected_status == "approved":
        query = query.where(ExpenseRequest.status == ExpenseStatus.APPROVED)
    elif selected_status == "auto_approved":
        query = query.where(ExpenseRequest.status == ExpenseStatus.AUTO_APPROVED)
    elif selected_status == "rejected":
        query = query.where(ExpenseRequest.status == ExpenseStatus.REJECTED)
    elif selected_status == "clarification":
        query = query.where(
            ExpenseRequest.status.in_([ExpenseStatus.CLARIFICATION_REQUIRED, ExpenseStatus.CLARIFICATION_RESPONDED])
        )
    else:
        query = query.where(
            ExpenseRequest.status.in_(
                [
                    ExpenseStatus.APPROVED,
                    ExpenseStatus.AUTO_APPROVED,
                    ExpenseStatus.REJECTED,
                    ExpenseStatus.CLARIFICATION_REQUIRED,
                    ExpenseStatus.CLARIFICATION_RESPONDED,
                ]
            )
        )

    if search:
        s = f"%{search.strip()}%"
        query = query.where(
            ExpenseRequest.request_id.ilike(s)
            | ExpenseRequest.purpose.ilike(s)
            | ExpenseRequest.description.ilike(s)
        )

    result = await db.execute(query.order_by(ExpenseRequest.updated_at.desc()))
    rows = result.scalars().all()

    history = []
    for row in rows:
        requestor = row.requestor
        requestor_info = {
            "first_name": requestor.first_name if requestor and requestor.first_name else "",
            "last_name": requestor.last_name if requestor and requestor.last_name else "",
            "email": requestor.email if requestor else "",
        }
        user_fallback = (
            f"{requestor_info['first_name']} {requestor_info['last_name']}".strip()
            or requestor_info["email"]
        )
        clarification_history = [
            {
                "id": c.id,
                "question": c.question,
                "response": c.response,
                "asked_at": to_ist(c.asked_at),
                "responded_at": to_ist(c.responded_at),
            }
            for c in sorted(row.clarifications or [], key=lambda item: item.asked_at or item.responded_at)
        ]

        history.append(
            {
                "id": row.request_id,
                "request_id": row.request_id,
                "db_id": row.id,
                "updated_at": to_ist(row.updated_at or row.created_at),
                "created_at": to_ist(row.created_at),
                "approved_at": to_ist(row.approved_at),
                "rejected_at": to_ist(row.rejected_at),
                "paid_at": to_ist(row.paid_at),
                "amount": round(float(row.amount), 2),
                "department": requestor.department.name if requestor and requestor.department else None,
                "requestor": requestor_info,
                "requestor_name": user_fallback,
                "requestor_email": requestor_info["email"],
                "user": user_fallback,
                "purpose": row.purpose,
                "description": row.description,
                "category": row.category.value if hasattr(row.category, "value") else row.category,
                "receipt_url": row.receipt_url,
                "payment_qr_url": row.payment_qr_url,
                "status": _status_for_admin_history(row.status),
                "clarification_history": clarification_history,
            }
        )

    return history


@router.get("/users")
async def list_users(
    branch_id: int | None = None,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    if not is_admin_like(current_user):
        raise HTTPException(status_code=403, detail="Access denied. Admin role required.")

    effective_branch_id = enforce_branch_scope(current_user, branch_id)

    query = select(User).options(selectinload(User.department), selectinload(User.branch)).where(
        User.org_id == current_user.org_id
    )
    if effective_branch_id is not None:
        query = query.where(User.branch_id == effective_branch_id)

    result = await db.execute(query.order_by(User.first_name))
    users = result.scalars().all()

    return [
        {
            "id": u.id,
            "first_name": u.first_name,
            "last_name": u.last_name,
            "full_name": f"{u.first_name} {u.last_name}".strip(),
            "email": u.email,
            "role": u.role.value if hasattr(u.role, "value") else u.role,
            "is_active": u.is_active,
            "department": (
                {"id": u.department.id, "name": u.department.name}
                if u.department else None
            ),
            "branch": (
                {"id": u.branch.id, "name": u.branch.name, "code": u.branch.code}
                if u.branch else None
            ),
            "branch_id": u.branch_id,
            "branch_name": u.branch.name if u.branch else None,
        }
        for u in users
    ]


@router.get("/expenses/{expense_id}")
async def get_expense_by_id(
    expense_id: str,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Fetch a single expense by DB integer ID or EXP-XXXXXXXX request_id."""
    if not is_admin_like(current_user):
        raise HTTPException(status_code=403, detail="Access denied. Admin role required.")

    # Try numeric DB id first, fall back to request_id string
    if expense_id.isdigit():
        filter_clause = (ExpenseRequest.id == int(expense_id))
    else:
        filter_clause = (ExpenseRequest.request_id == expense_id)

    result = await db.execute(
        select(ExpenseRequest).options(
            selectinload(ExpenseRequest.requestor).selectinload(User.department),
            selectinload(ExpenseRequest.approver),
            selectinload(ExpenseRequest.clarifications),
        ).where(
            filter_clause,
            ExpenseRequest.org_id == current_user.org_id,
        )
    )
    row = result.scalar_one_or_none()
    if not row:
        raise HTTPException(status_code=404, detail="Expense not found.")

    requestor = row.requestor
    clarification_history = [
        {
            "id": c.id,
            "question": c.question,
            "response": c.response,
            "asked_at": to_ist(c.asked_at),
            "responded_at": to_ist(c.responded_at),
        }
        for c in sorted(row.clarifications or [], key=lambda c: c.asked_at or c.responded_at)
    ]

    return {
        "id": row.request_id,
        "request_id": row.request_id,
        "db_id": row.id,
        "created_at": to_ist(row.created_at),
        "updated_at": to_ist(row.updated_at or row.created_at),
        "approved_at": to_ist(row.approved_at),
        "rejected_at": to_ist(row.rejected_at),
        "paid_at": to_ist(row.paid_at),
        "amount": round(float(row.amount), 2),
        "purpose": row.purpose,
        "description": row.description,
        "category": row.category.value if hasattr(row.category, "value") else row.category,
        "request_type": row.request_type.value if hasattr(row.request_type, "value") else row.request_type,
        "status": row.status.value if hasattr(row.status, "value") else row.status,
        "rejection_reason": row.rejection_reason,
        "receipt_url": row.receipt_url,
        "payment_qr_url": row.payment_qr_url,
        "payment_method": row.payment_method,
        "transaction_reference": row.transaction_reference,
        "department": requestor.department.name if requestor and requestor.department else None,
        "requestor": {
            "first_name": requestor.first_name if requestor else "",
            "last_name": requestor.last_name if requestor else "",
            "email": requestor.email if requestor else "",
        },
        "requestor_name": f"{requestor.first_name} {requestor.last_name}".strip() if requestor else "",
        "approver": {
            "first_name": row.approver.first_name,
            "last_name": row.approver.last_name,
            "email": row.approver.email,
        } if row.approver else None,
        "clarification_history": clarification_history,
    }
