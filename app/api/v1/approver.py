from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy.orm import selectinload
from sqlalchemy import func
from typing import List
from app.db.session import get_db
from app.models.expense import ExpenseRequest, ExpenseStatus, ClarificationHistory
from app.models.user import UserRole
from app.schemas.expense import ExpenseOut, ClarificationCreate
from app.core.security import get_current_user
import datetime

router = APIRouter(prefix="/approver", tags=["approver"])

class ClarificationRequest(BaseModel):
    expense_id: int
    question: str

@router.get("/org-expenses", response_model=List[ExpenseOut])
async def get_org_expenses(
    status: str = None,
    payment_status: str = None,
    db: AsyncSession = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """
    Get ALL expense requests for the organization (Admin/Approver only).
    Optional filters:
    - status: pending, approved, rejected, clarification_required, clarification_responded
    - payment_status: pending, paid
    """
    # Role Check
    if current_user.role not in [UserRole.ADMIN, UserRole.APPROVER]:
        raise HTTPException(status_code=403, detail="Access denied. Approver privileges required.")

    query = select(ExpenseRequest).options(
        selectinload(ExpenseRequest.clarifications),
        selectinload(ExpenseRequest.requestor)
    ).where(ExpenseRequest.org_id == current_user.org_id)
    
    # Filter by Approval Status
    if status and status.lower() != "all":
        s = status.lower()
        if s == "approved":
            query = query.where(ExpenseRequest.status.in_(["approved", "auto_approved"]))
        elif s == "clarification":
            query = query.where(ExpenseRequest.status.in_(["clarification_required", "clarification_responded"]))
        else:
            query = query.where(ExpenseRequest.status == s)

    # Filter by Payment Status
    if payment_status and payment_status.lower() != "all":
        ps = payment_status.lower()
        if ps == "pending":
            # Pending payment means approved but not yet paid
            query = query.where(ExpenseRequest.status.in_(["approved", "auto_approved"]))
        elif ps == "paid":
            query = query.where(ExpenseRequest.status == "paid")

    result = await db.execute(query.order_by(ExpenseRequest.created_at.desc()))
    return result.scalars().all()

@router.get("/dashboard-stats")
async def get_approver_stats(db: AsyncSession = Depends(get_db), current_user = Depends(get_current_user)):
    # Count pending requests
    pending_query = select(func.count(ExpenseRequest.id)).where(
        ExpenseRequest.status == ExpenseStatus.PENDING
    )
    # Sum of approved amounts by this admin
    approved_amount_query = select(func.sum(ExpenseRequest.amount)).where(
        ExpenseRequest.approver_id == current_user.id,
        ExpenseRequest.status == ExpenseStatus.APPROVED
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
    db: AsyncSession = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """
    Approve or reject an expense request.
    """
    # 1. Role Check
    if current_user.role not in [UserRole.ADMIN, UserRole.APPROVER]:
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
        approved_at = datetime.datetime.utcnow()
        message = f"Expense request {expense.request_id} approved."
    else:
        expense.status = ExpenseStatus.REJECTED
        expense.rejection_reason = decision.rejection_reason
        expense.approver_id = current_user.id
        message = f"Expense request {expense.request_id} rejected."
    
    try:
        await db.commit()
        await db.refresh(expense)
    except Exception as e:
        await db.rollback()
        raise HTTPException(status_code=500, detail=f"Failed to update expense: {str(e)}")
    
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
    db: AsyncSession = Depends(get_db)
):
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
    return {"msg": "Clarification sent to requester"}

@router.get("/history/{expense_id}")
async def get_clarification_history(expense_id: int, db: AsyncSession = Depends(get_db)):
    query = select(ClarificationHistory).where(
        ClarificationHistory.expense_id == expense_id
    ).order_by(ClarificationHistory.asked_at.asc())
    
    result = await db.execute(query)
    return result.scalars().all()