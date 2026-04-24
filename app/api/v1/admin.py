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
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    if current_user.role != UserRole.ADMIN:
        raise HTTPException(status_code=403, detail="Access denied. Admin role required.")

    pending_query = select(func.count(ExpenseRequest.id)).where(
        ExpenseRequest.org_id == current_user.org_id,
        ExpenseRequest.status.in_([ExpenseStatus.PENDING, ExpenseStatus.CLARIFICATION_RESPONDED]),
    )
    pending_requests = int((await db.execute(pending_query)).scalar() or 0)

    approved_amount_query = select(func.sum(ExpenseRequest.amount)).where(
        ExpenseRequest.org_id == current_user.org_id,
        ExpenseRequest.status.in_([ExpenseStatus.APPROVED, ExpenseStatus.AUTO_APPROVED, ExpenseStatus.PAID]),
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
    unassigned_users = int((await db.execute(unassigned_users_query)).scalar() or 0)

    return {
        "user": {
            "shortName": current_user.first_name,
        },
        "overview": {
            "pendingRequestsCount": pending_requests,
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
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    if current_user.role != UserRole.ADMIN:
        raise HTTPException(status_code=403, detail="Access denied. Admin role required.")

    query = select(ExpenseRequest).options(
        selectinload(ExpenseRequest.requestor),
        selectinload(ExpenseRequest.clarifications),
    ).where(
        ExpenseRequest.org_id == current_user.org_id
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
                "asked_at": c.asked_at.isoformat() if c.asked_at else None,
                "responded_at": c.responded_at.isoformat() if c.responded_at else None,
            }
            for c in sorted(row.clarifications or [], key=lambda item: item.asked_at or item.responded_at)
        ]

        history.append(
            {
                "id": row.request_id,
                "request_id": row.request_id,
                "updated_at": (row.updated_at or row.created_at).isoformat(),
                "amount": round(float(row.amount), 2),
                "requestor": requestor_info,
                "user": user_fallback,
                "purpose": row.purpose,
                "status": _status_for_admin_history(row.status),
                "clarification_history": clarification_history,
            }
        )

    return history
