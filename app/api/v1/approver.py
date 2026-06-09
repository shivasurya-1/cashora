from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy.orm import selectinload
from sqlalchemy import func
from typing import List, Optional
from app.db.session import get_db
from app.models.expense import ExpenseRequest, ExpenseStatus, ClarificationHistory
from app.models.notification import UserDeviceToken
from app.models.user import UserRole, User
from app.schemas.expense import ExpenseOut, ClarificationCreate
from app.services.push_service import dispatch_push_notifications
from app.core.security import get_current_user
from app.core.roles import enforce_branch_scope, is_admin_like
from app.core.utils import to_ist
import datetime

router = APIRouter(prefix="/approver", tags=["approver"])

class ClarificationRequest(BaseModel):
    expense_id: int
    question: str

@router.get("/org-expenses")
async def get_org_expenses(
    status: str = None,
    payment_status: str = None,
    branch_id: int | None = None,
    db: AsyncSession = Depends(get_db),
    current_user = Depends(get_current_user)
):
    if str(current_user.role) not in [UserRole.ADMIN.value, UserRole.SUPER_ADMIN.value, UserRole.APPROVER.value]:
        raise HTTPException(status_code=403, detail="Access denied. Approver privileges required.")

    effective_branch_id = None
    if is_admin_like(current_user):
        effective_branch_id = enforce_branch_scope(current_user, branch_id)
    else:
        if branch_id is not None and branch_id != current_user.branch_id:
            raise HTTPException(status_code=403, detail="Cannot access another branch.")
        effective_branch_id = current_user.branch_id

    query = select(ExpenseRequest).options(
        selectinload(ExpenseRequest.clarifications),
        selectinload(ExpenseRequest.requestor).selectinload(User.department),
        selectinload(ExpenseRequest.approver),
    ).where(ExpenseRequest.org_id == current_user.org_id)

    if effective_branch_id is not None:
        query = query.where(
            ExpenseRequest.user_id.in_(
                select(User.id).where(User.branch_id == effective_branch_id)
            )
        )

    if status and status.lower() != "all":
        s = status.lower()
        if s == "approved":
            query = query.where(ExpenseRequest.status.in_(["approved", "auto_approved"]))
        elif s == "clarification":
            query = query.where(ExpenseRequest.status.in_(["clarification_required", "clarification_responded"]))
        else:
            query = query.where(ExpenseRequest.status == s)

    if payment_status and payment_status.lower() != "all":
        ps = payment_status.lower()
        if ps == "pending":
            query = query.where(ExpenseRequest.status.in_(["approved", "auto_approved"]))
        elif ps == "paid":
            query = query.where(ExpenseRequest.status == "paid")

    result = await db.execute(query.order_by(ExpenseRequest.created_at.desc()))
    rows = result.scalars().all()

    def _payment_status(row):
        if row.status == ExpenseStatus.PAID:
            return "paid"
        if row.status in [ExpenseStatus.APPROVED, ExpenseStatus.AUTO_APPROVED]:
            return "pending"
        return None

    return [
        {
            "id": row.id,
            "request_id": row.request_id,
            "amount": round(float(row.amount), 2),
            "purpose": row.purpose,
            "description": row.description,
            "category": row.category.value if hasattr(row.category, "value") else row.category,
            "request_type": row.request_type.value if hasattr(row.request_type, "value") else row.request_type,
            "status": row.status.value if hasattr(row.status, "value") else row.status,
            "payment_status": _payment_status(row),
            "rejection_reason": row.rejection_reason,
            "receipt_url": row.receipt_url,
            "payment_qr_url": row.payment_qr_url,
            "payment_method": row.payment_method,
            "transaction_reference": row.transaction_reference,
            "department": row.requestor.department.name if row.requestor and row.requestor.department else None,
            "requestor": {
                "first_name": row.requestor.first_name if row.requestor else "",
                "last_name": row.requestor.last_name if row.requestor else "",
                "email": row.requestor.email if row.requestor else "",
            },
            "requestor_name": f"{row.requestor.first_name} {row.requestor.last_name}".strip() if row.requestor else "",
            "created_at": to_ist(row.created_at),
            "approved_at": to_ist(row.approved_at),
            "rejected_at": to_ist(row.rejected_at),
            "paid_at": to_ist(row.paid_at),
            "clarifications": [
                {
                    "id": c.id,
                    "question": c.question,
                    "response": c.response or "",
                    "asked_at": to_ist(c.asked_at),
                    "responded_at": to_ist(c.responded_at) or "",
                }
                for c in sorted(row.clarifications or [], key=lambda x: x.asked_at)
            ],
        }
        for row in rows
    ]

@router.get("/dashboard-stats")
async def get_approver_stats(db: AsyncSession = Depends(get_db), current_user = Depends(get_current_user)):
    effective_branch_id = current_user.branch_id

    # Count pending requests in this org assigned to this approver
    pending_query = select(func.count(ExpenseRequest.id)).where(
        ExpenseRequest.org_id == current_user.org_id,
        ExpenseRequest.status.in_([ExpenseStatus.PENDING, ExpenseStatus.CLARIFICATION_RESPONDED]),
    )

    if effective_branch_id is not None:
        pending_query = pending_query.where(
            ExpenseRequest.user_id.in_(
                select(User.id).where(User.branch_id == effective_branch_id)
            )
        )

    # Sum of approved amounts by this admin
    approved_amount_query = select(func.sum(ExpenseRequest.amount)).where(
        ExpenseRequest.approver_id == current_user.id,
        ExpenseRequest.status == ExpenseStatus.APPROVED
    )
    if effective_branch_id is not None:
        approved_amount_query = approved_amount_query.where(
            ExpenseRequest.user_id.in_(
                select(User.id).where(User.branch_id == effective_branch_id)
            )
        )
    
    pending_count = (await db.execute(pending_query)).scalar() or 0
    total_approved = (await db.execute(approved_amount_query)).scalar() or 0
    
    return {
        "pending_count": pending_count,
        "total_approved_amount": total_approved
    }


class ApprovalDecisionRequest(BaseModel):
    """Request body for approving or rejecting an expense"""
    action: str  # 'approve' or 'reject'
    rejection_reason: str | None = None  # Required if action is 'reject'

class ApprovalDecisionResponse(BaseModel):
    """Response body after processing approval/rejection"""
    success: bool
    message: str
    expense_id: int
    request_id: str
    new_status: str
    approver_name: str
    approved_at: datetime.datetime | None = None

@router.post("/expenses/{expense_id}/decision", response_model=ApprovalDecisionResponse)
async def approve_or_reject_expense(
    expense_id: int,
    decision: ApprovalDecisionRequest,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """
    Approve or reject an expense request.
    """
    # 1. Role Check
    if str(current_user.role) not in [UserRole.ADMIN.value, UserRole.SUPER_ADMIN.value, UserRole.APPROVER.value]:
        raise HTTPException(
            status_code=403, 
            detail="Access denied. Only Admin or Approver can approve/reject expense requests."
        )
    
    # 2. Validate action
    action = decision.action.lower()
    if action not in ['approve', 'reject']:
        raise HTTPException(
            status_code=400,
            detail="Invalid action. Must be 'approve' or 'reject'."
        )
    
    # 3. Validate rejection reason
    if action == 'reject' and not decision.rejection_reason:
        raise HTTPException(
            status_code=400,
            detail="Rejection reason is required when rejecting an expense request."
        )
    
    # 4. Fetch the expense request
    query = select(ExpenseRequest).where(
        ExpenseRequest.id == expense_id,
        ExpenseRequest.org_id == current_user.org_id
    )
    result = await db.execute(query)
    expense = result.scalar_one_or_none()
    
    if not expense:
        raise HTTPException(
            status_code=404, 
            detail=f"Expense request with ID {expense_id} not found."
        )
    
    # 5. Check if valid state
    if expense.status not in [ExpenseStatus.PENDING, ExpenseStatus.CLARIFICATION_RESPONDED]:
        raise HTTPException(
            status_code=400,
            detail=f"Cannot {action} expense. Current status is '{expense.status}'."
        )
    
    # 6. Process decision
    approved_at = None
    if action == 'approve':
        expense.status = ExpenseStatus.APPROVED
        expense.approver_id = current_user.id
        expense.approved_at = datetime.datetime.utcnow()
        approved_at = expense.approved_at
        message = f"Expense request {expense.request_id} approved."
    else:
        expense.status = ExpenseStatus.REJECTED
        expense.rejection_reason = decision.rejection_reason
        expense.approver_id = current_user.id
        expense.rejected_at = datetime.datetime.utcnow()
        message = f"Expense request {expense.request_id} rejected."
    
    try:
        await db.commit()
        await db.refresh(expense)
    except Exception as e:
        await db.rollback()
        raise HTTPException(status_code=500, detail=f"Failed to update expense: {str(e)}")
    
    # Push notification to requestor
    token_result = await db.execute(
        select(UserDeviceToken.token).where(
            UserDeviceToken.user_id == expense.user_id,
            UserDeviceToken.is_active.is_(True),
        )
    )
    requestor_tokens = [r[0] for r in token_result.all()]
    if requestor_tokens:
        if action == "approve":
            push_title = "Expense Approved ✅"
            push_body = f"Your ₹{round(float(expense.amount), 0):,.0f} expense for {expense.purpose} was approved."
            event_type = "expense_approved"
        else:
            push_title = "Expense Rejected ❌"
            push_body = f"Your ₹{round(float(expense.amount), 0):,.0f} expense for {expense.purpose} was rejected."
            event_type = "expense_rejected"
        background_tasks.add_task(
            dispatch_push_notifications,
            tokens=requestor_tokens,
            title=push_title,
            body=push_body,
            data={
                "event_type": event_type,
                "expense_id": str(expense.id),
                "request_id": expense.request_id,
                "status": expense.status.value,
            },
        )

    return ApprovalDecisionResponse(
        success=True,
        message=message,
        expense_id=expense.id,
        request_id=expense.request_id,
        new_status=expense.status.value,
        approver_name=f"{current_user.first_name} {current_user.last_name}",
        approved_at=approved_at
    )


@router.post("/ask-clarification")
async def ask_clarification(
    data: ClarificationRequest,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    current_user = Depends(get_current_user)
):
    if str(current_user.role) not in [UserRole.ADMIN.value, UserRole.SUPER_ADMIN.value, UserRole.APPROVER.value]:
        raise HTTPException(status_code=403, detail="Access denied. Admin or Approver role required.")
    # Create history record
    new_chat = ClarificationHistory(
        expense_id=data.expense_id,
        question=data.question
    )
    # Update status
    query = select(ExpenseRequest).where(ExpenseRequest.id == data.expense_id)
    result = await db.execute(query)
    expense = result.scalar_one_or_none()
    
    if not expense:
        raise HTTPException(status_code=404, detail="Expense request not found")
    
    expense.status = ExpenseStatus.CLARIFICATION_REQUIRED
    
    db.add(new_chat)
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
            title="Clarification Needed 💬",
            body=f"Your approver has a question about expense {expense.request_id}.",
            data={
                "event_type": "clarification_required",
                "expense_id": str(expense.id),
                "request_id": expense.request_id,
                "status": "clarification_required",
            },
        )

    return {"msg": "Clarification sent to requester"}

@router.get("/history/{expense_id}")
async def get_clarification_history(
    expense_id: int,
    db: AsyncSession = Depends(get_db),
    current_user = Depends(get_current_user)
):
    if str(current_user.role) not in [UserRole.ADMIN.value, UserRole.SUPER_ADMIN.value, UserRole.APPROVER.value]:
        raise HTTPException(status_code=403, detail="Access denied. Admin or Approver role required.")

    # Load the expense with requestor and approver to get names
    expense_result = await db.execute(
        select(ExpenseRequest).options(
            selectinload(ExpenseRequest.requestor),
            selectinload(ExpenseRequest.approver),
        ).where(ExpenseRequest.id == expense_id)
    )
    expense = expense_result.scalar_one_or_none()
    if not expense:
        raise HTTPException(status_code=404, detail="Expense not found.")

    asked_by = (
        f"{expense.approver.first_name} {expense.approver.last_name}".strip()
        if expense.approver else "Admin"
    )
    responded_by = (
        f"{expense.requestor.first_name} {expense.requestor.last_name}".strip()
        if expense.requestor else "Requestor"
    )

    query = select(ClarificationHistory).where(
        ClarificationHistory.expense_id == expense_id
    ).order_by(ClarificationHistory.asked_at.asc())
    result = await db.execute(query)
    rows = result.scalars().all()

    return [
        {
            "id": c.id,
            "question": c.question,
            "asked_by": asked_by,
            "asked_at": to_ist(c.asked_at) or "",
            "response": c.response or "",
            "responded_by": responded_by,
            "responded_at": to_ist(c.responded_at) or "",
        }
        for c in rows
    ]