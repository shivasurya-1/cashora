import uuid
from datetime import datetime
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy.orm import selectinload
from app.models.expense import ExpenseRequest, ExpenseStatus
from app.models.organization import Organization
from app.schemas.expense import ExpenseCreate

class ExpenseService:
    @staticmethod
    async def create_new_request(db: AsyncSession, expense_in: ExpenseCreate, user_id: int, org_id: int):
        # 1. Fetch Organization Settings for Deemed Approval Limit
        query = select(Organization).where(Organization.id == org_id)
        result = await db.execute(query)
        org = result.scalar_one_or_none()
        
        deemed_limit = org.deemed_approval_limit if org else 0.0

        # 2. Logic for Auto-Approval
        approval_status = ExpenseStatus.PENDING
        if expense_in.amount <= deemed_limit:
            approval_status = ExpenseStatus.AUTO_APPROVED

        # 3. Generate Request ID
        short_uuid = str(uuid.uuid4())[:8].upper()
        request_id = f"EXP-{short_uuid}"

        new_expense = ExpenseRequest(
            **expense_in.model_dump(),
            request_id=request_id,
            status=approval_status,
            user_id=user_id,
            org_id=org_id
        )

        db.add(new_expense)
        await db.commit()
        
        # Refresh with eagerly loaded relationships
        await db.refresh(new_expense, attribute_names=["clarifications", "requestor"])
        
        return new_expense