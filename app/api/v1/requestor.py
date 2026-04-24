from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, UploadFile, File, Form
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy.orm import selectinload
from sqlalchemy import func
from typing import List, Optional
from app.db.session import get_db
from app.models.expense import ExpenseRequest, ExpenseCategory, ExpenseStatus, ClarificationHistory
from app.models.notification import UserDeviceToken
from app.models.organization import Organization
from app.models.user import User, UserRole
from app.schemas.expense import ExpenseCreate, ExpenseOut, ClarificationOut
from app.services.expense_service import ExpenseService
from app.services.cloudinary_service import cloudinary_service
from app.services.push_service import dispatch_push_notifications
from app.core.security import get_current_user # Dependency to get logged-in user
import datetime

router = APIRouter(prefix="/requestor", tags=["requestor"])


def _status_for_requestor_ui(status: ExpenseStatus) -> str:
    if status == ExpenseStatus.APPROVED:
        return "approved"
    if status == ExpenseStatus.AUTO_APPROVED:
        return "auto_approved"
    if status == ExpenseStatus.REJECTED:
        return "rejected"
    if status in [ExpenseStatus.CLARIFICATION_REQUIRED, ExpenseStatus.CLARIFICATION_RESPONDED]:
        return "clarification"
    if status == ExpenseStatus.PAID:
        return "approved"
    return "pending"


@router.get("/dashboard")
async def get_requestor_dashboard(
    db: AsyncSession = Depends(get_db),
    current_user = Depends(get_current_user)
):
    if current_user.role != UserRole.REQUESTOR:
        raise HTTPException(status_code=403, detail="Access denied. Requestor role required.")

    today = datetime.datetime.utcnow()
    month_start = datetime.datetime(today.year, today.month, 1)
    next_month = (month_start.replace(day=28) + datetime.timedelta(days=4)).replace(day=1)

    spent_query = select(func.sum(ExpenseRequest.amount)).where(
        ExpenseRequest.user_id == current_user.id,
        ExpenseRequest.status == ExpenseStatus.PAID,
        ExpenseRequest.updated_at >= month_start,
        ExpenseRequest.updated_at < next_month,
    )
    amount_spent = float((await db.execute(spent_query)).scalar() or 0)

    org_query = select(Organization).where(Organization.id == current_user.org_id)
    org_result = await db.execute(org_query)
    org = org_result.scalar_one_or_none()
    monthly_limit = float(org.deemed_approval_limit if org else 0.0)

    progress_ratio = 0.0
    if monthly_limit > 0:
        progress_ratio = min(amount_spent / monthly_limit, 1.0)

    pending_query = select(func.count(ExpenseRequest.id)).where(
        ExpenseRequest.user_id == current_user.id,
        ExpenseRequest.status.in_([ExpenseStatus.PENDING, ExpenseStatus.CLARIFICATION_RESPONDED]),
    )
    pending_count = int((await db.execute(pending_query)).scalar() or 0)

    recent_query = (
        select(ExpenseRequest)
        .where(ExpenseRequest.user_id == current_user.id)
        .order_by(ExpenseRequest.created_at.desc())
        .limit(5)
    )
    recent_result = await db.execute(recent_query)
    recent_requests = recent_result.scalars().all()

    return {
        "user": {
            "shortName": current_user.first_name,
        },
        "monthlyExpense": {
            "amountSpent": round(amount_spent, 2),
            "monthlyLimit": round(monthly_limit, 2),
            "progressRatio": round(progress_ratio, 4),
        },
        "pendingApprovals": {
            "pendingCount": pending_count,
        },
        "recentRequests": [
            {
                "id": r.request_id,
                "purpose": r.purpose,
                "date": (r.updated_at or r.created_at).isoformat(),
                "amount": round(float(r.amount), 2),
                "status": _status_for_requestor_ui(r.status),
                "category": r.category.value,
            }
            for r in recent_requests
        ],
    }


@router.get("/requests")
async def get_requestor_requests(
    search: Optional[str] = None,
    status: Optional[str] = "All",
    db: AsyncSession = Depends(get_db),
    current_user = Depends(get_current_user)
):
    if current_user.role != UserRole.REQUESTOR:
        raise HTTPException(status_code=403, detail="Access denied. Requestor role required.")

    query = select(ExpenseRequest).where(ExpenseRequest.user_id == current_user.id)

    selected_status = (status or "All").strip().lower()
    if selected_status not in ["all", "pending", "clarification", "approved", "rejected", "unpaid"]:
        raise HTTPException(status_code=400, detail="Invalid status filter")

    if selected_status == "pending":
        query = query.where(ExpenseRequest.status == ExpenseStatus.PENDING)
    elif selected_status == "clarification":
        query = query.where(
            ExpenseRequest.status.in_([ExpenseStatus.CLARIFICATION_REQUIRED, ExpenseStatus.CLARIFICATION_RESPONDED])
        )
    elif selected_status == "approved":
        query = query.where(
            ExpenseRequest.status.in_([ExpenseStatus.APPROVED, ExpenseStatus.AUTO_APPROVED, ExpenseStatus.PAID])
        )
    elif selected_status == "rejected":
        query = query.where(ExpenseRequest.status == ExpenseStatus.REJECTED)
    elif selected_status == "unpaid":
        query = query.where(ExpenseRequest.status.in_([ExpenseStatus.APPROVED, ExpenseStatus.AUTO_APPROVED]))

    if search:
        s = f"%{search.strip()}%"
        query = query.where(
            ExpenseRequest.request_id.ilike(s)
            | ExpenseRequest.purpose.ilike(s)
            | ExpenseRequest.description.ilike(s)
        )

    result = await db.execute(query.order_by(ExpenseRequest.created_at.desc()))
    rows = result.scalars().all()

    return [
        {
            "id": r.request_id,
            "purpose": r.purpose,
            "date": (r.updated_at or r.created_at).isoformat(),
            "category": r.category.value,
            "amount": round(float(r.amount), 2),
            "status": _status_for_requestor_ui(r.status),
            "rejection_reason": r.rejection_reason if r.status == ExpenseStatus.REJECTED else None,
        }
        for r in rows
    ]

@router.get("/history/{expense_id}", response_model=List[ClarificationOut])
async def get_clarification_history(
    expense_id: int, 
    db: AsyncSession = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """
    Get clarification history (Q&A) for a specific expense.
    Ensures the user owns the expense.
    """
    # Verify ownership
    expense_query = select(ExpenseRequest).where(
        ExpenseRequest.id == expense_id,
        ExpenseRequest.user_id == current_user.id
    )
    result = await db.execute(expense_query)
    expense = result.scalar_one_or_none()
    
    if not expense:
         raise HTTPException(status_code=404, detail="Expense not found or access denied")

    query = select(ClarificationHistory).where(
        ClarificationHistory.expense_id == expense_id
    ).order_by(ClarificationHistory.asked_at.asc())
    
    result = await db.execute(query)
    return result.scalars().all()

@router.get("/categories")
async def get_expense_categories():
    """Get list of available expense categories"""
    return [category.value for category in ExpenseCategory]

@router.post("/submit", response_model=ExpenseOut)
async def submit_expense(
    amount: float = Form(...),
    purpose: str = Form(...),
    category: str = Form(...),
    request_type: str = Form("pre_approved"),
    description: str = Form(None),
    receipt_file: UploadFile = File(None),
    payment_qr_file: UploadFile = File(None),
    payment_note: str = Form(None),
    # Accept generic frontend file fields: 'file'
    generic_files: list[UploadFile] = File(None, alias="file"),
    db: AsyncSession = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """
    Submit an expense request.
    """
    receipt_url = None
    payment_qr_url = None

    # If frontend uses generic 'file' fields
    if generic_files:
        if not receipt_file:
            receipt_file = generic_files[0]
        if len(generic_files) > 1 and not payment_qr_file:
            payment_qr_file = generic_files[1]

    # Handle Receipt Upload if provided
    if receipt_file:
        allowed_types = [
            "image/jpeg", "image/jpg", "image/png", "image/gif", "application/pdf",
            "image/heic", "image/heif", "image/webp"
        ]
        # Debug logging to help identify why validation fails
        print(f"DEBUG: Processing receipt_file: {receipt_file.filename}, Content-Type: {receipt_file.content_type}")
        
        if receipt_file.content_type not in allowed_types:
            raise HTTPException(
                status_code=400, 
                detail=f"FileType: {receipt_file.content_type} not allowed. Supported types: JPEG, JPG, PNG, GIF, PDF"
            )
        file_content = await receipt_file.read()
        if len(file_content) > 10 * 1024 * 1024:
            raise HTTPException(status_code=400, detail="Receipt file size exceeds 10MB limit")
        try:
            upload_result = cloudinary_service.upload_receipt(
                file_content=file_content,
                filename=receipt_file.filename,
                expense_id="new_request"
            )
            receipt_url = upload_result["url"]
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Failed to upload receipt: {str(e)}")

    # Handle Payment QR Upload if provided
    if payment_qr_file:
        allowed_types = [
            "image/jpeg", "image/jpg", "image/png", "image/gif", "application/pdf",
            "image/heic", "image/heif", "image/webp"
        ]
        print(f"DEBUG: Processing payment_qr_file: {payment_qr_file.filename}, Content-Type: {payment_qr_file.content_type}")
        
        if payment_qr_file.content_type not in allowed_types:
             raise HTTPException(status_code=400, detail=f"FileType: {payment_qr_file.content_type} not allowed for Payment QR.")
        qr_content = await payment_qr_file.read()
        if len(qr_content) > 5 * 1024 * 1024:
            raise HTTPException(status_code=400, detail="Payment QR file size exceeds 5MB limit")
        try:
            upload_result = cloudinary_service.upload_receipt(
                file_content=qr_content,
                filename=f"qr_{payment_qr_file.filename}",
                expense_id="new_request_qr"
            )
            payment_qr_url = upload_result["url"]
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Failed to upload payment QR: {str(e)}")

    # Validation: If the request is post_approved, require a receipt
    rt = (request_type or "").lower()
    if rt == "post_approved" and not receipt_url:
        raise HTTPException(status_code=400, detail="Receipt required for post_approved requests.")

    try:
        expense_data = ExpenseCreate(
            amount=amount,
            purpose=purpose,
            category=category,
            request_type=request_type,
            description=description,
            receipt_url=receipt_url,
            payment_qr_url=payment_qr_url,
            payment_note=payment_note
        )
    except ValueError as e:
         raise HTTPException(status_code=400, detail=f"Invalid data: {str(e)}")

    # Call Service
    return await ExpenseService.create_new_request(
        db, expense_data, current_user.id, current_user.org_id
    )

@router.get("/my-requests", response_model=List[ExpenseOut])
async def get_my_requests(
    status: str = None,
    payment_status: str = None,
    db: AsyncSession = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """
    Get all expense requests for the current user.
    Optional filters:
    - status: pending, approved, rejected, etc.
    - payment_status: pending, paid, etc. (maps to expense status for now)
    """
    query = select(ExpenseRequest).options(
        selectinload(ExpenseRequest.clarifications),
        selectinload(ExpenseRequest.requestor)
    ).where(ExpenseRequest.user_id == current_user.id)
    
    # Filter by Approval Status
    if status and status != "All":
        s = status.lower()
        if s == "approved":
            query = query.where(ExpenseRequest.status.in_(["approved", "auto_approved"]))
        elif s == "clarification":
            query = query.where(ExpenseRequest.status.in_(["clarification_required", "clarification_responded"]))
        else:
            query = query.where(ExpenseRequest.status == s)

    # Filter by Payment Status
    if payment_status and payment_status != "All":
        ps = payment_status.lower()
        if ps == "pending":
            # Pending payment means approved but not yet paid
            query = query.where(ExpenseRequest.status.in_(["approved", "auto_approved"]))
        elif ps == "paid":
            query = query.where(ExpenseRequest.status == "paid")

    result = await db.execute(query.order_by(ExpenseRequest.created_at.desc()))
    return result.scalars().all()

class ClarificationResponseModel(BaseModel):
    response_text: str

@router.post("/respond-clarification/{expense_id}")
async def respond_to_admin(
    expense_id: int, 
    data: ClarificationResponseModel, 
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """
    Respond to the latest clarification question for an expense.
    """
    # Verify ownership
    expense_query = select(ExpenseRequest).where(
        ExpenseRequest.id == expense_id,
        ExpenseRequest.user_id == current_user.id
    )
    result = await db.execute(expense_query)
    expense = result.scalar_one_or_none()
    
    if not expense:
        raise HTTPException(status_code=404, detail="Expense not found or access denied")
    
    # Find the latest unanswered clarification
    query = select(ClarificationHistory).where(
        ClarificationHistory.expense_id == expense_id,
        ClarificationHistory.response == None
    ).order_by(ClarificationHistory.asked_at.desc())
    
    result = await db.execute(query)
    history = result.scalars().first()
    
    if not history:
        raise HTTPException(status_code=404, detail="No pending clarification found for this expense")

    history.response = data.response_text
    history.responded_at = datetime.datetime.now()
    
    # Update expense status to "Responded"
    expense.status = ExpenseStatus.CLARIFICATION_RESPONDED
    
    await db.commit()

    # Notify all approvers/admins in the org that clarification response was submitted.
    approver_query = select(User.id).where(
        User.org_id == current_user.org_id,
        User.role.in_([UserRole.ADMIN, UserRole.APPROVER]),
        User.is_active.is_(True),
    )
    approver_result = await db.execute(approver_query)
    approver_ids = [row[0] for row in approver_result.all()]

    if approver_ids:
        token_query = select(UserDeviceToken.token).where(
            UserDeviceToken.user_id.in_(approver_ids),
            UserDeviceToken.is_active.is_(True),
        )
        token_result = await db.execute(token_query)
        target_tokens = [row[0] for row in token_result.all()]

        if target_tokens:
            background_tasks.add_task(
                dispatch_push_notifications,
                tokens=target_tokens,
                title="Clarification Responded",
                body=f"Requester responded for expense {expense.request_id}.",
                data={
                    "event_type": "clarification_responded",
                    "expense_id": str(expense.id),
                    "request_id": expense.request_id,
                    "status": expense.status.value,
                },
            )

    return {"msg": "Response submitted successfully"}

@router.post("/upload-receipt/{expense_id}")
async def upload_receipt(
    expense_id: int,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """
    Upload a receipt/bill for an expense request
    """
    # Validate file type
    allowed_types = ["image/jpeg", "image/png", "image/gif", "application/pdf"]
    if file.content_type not in allowed_types:
        raise HTTPException(
            status_code=400,
            detail=f"File type not allowed. Supported types: JPEG, PNG, GIF, PDF"
        )
    
    # Validate file size (max 10MB)
    file_content = await file.read()
    if len(file_content) > 10 * 1024 * 1024:  # 10MB
        raise HTTPException(
            status_code=400,
            detail="File size exceeds 10MB limit"
        )
    
    # Get the expense request
    query = select(ExpenseRequest).where(
        ExpenseRequest.id == expense_id,
        ExpenseRequest.user_id == current_user.id
    )
    result = await db.execute(query)
    expense = result.scalar_one_or_none()
    
    if not expense:
        raise HTTPException(
            status_code=404,
            detail="Expense request not found or you don't have permission to update it"
        )
    
    try:
        # Upload to Cloudinary
        upload_result = cloudinary_service.upload_receipt(
            file_content=file_content,
            filename=file.filename,
            expense_id=expense.request_id
        )
        
        # Update expense with receipt URL
        expense.receipt_url = upload_result["url"]
        await db.commit()
        
        return {
            "msg": "Receipt uploaded successfully",
            "receipt_url": upload_result["url"],
            "file_size": upload_result["size"],
            "format": upload_result["format"]
        }
        
    except Exception as e:
        await db.rollback()
        raise HTTPException(
            status_code=500,
            detail=f"Failed to upload receipt: {str(e)}"
        )


@router.post("/upload-payment-qr/{expense_id}")
async def upload_payment_qr(
    expense_id: int,
    file: UploadFile = File(...),
    payment_note: Optional[str] = Form(None),
    db: AsyncSession = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """
    Upload a payment QR code for an approved expense request.
    This allows the accountant to download it and pay manually.
    """
    # 1. Validate file type
    allowed_types = [
        "image/jpeg", "image/jpg", "image/png", "image/gif", "application/pdf",
        "image/heic", "image/heif", "image/webp"
    ]
    print(f"DEBUG: Processing upload_payment_qr: {file.filename}, Content-Type: {file.content_type}")
    
    if file.content_type not in allowed_types:
        raise HTTPException(
            status_code=400, 
            detail=f"FileType: {file.content_type} not allowed. Supported: JPEG, JPG, PNG, GIF, PDF"
        )
    
    # 2. Validate file size (max 5MB for QR)
    file_content = await file.read()
    if len(file_content) > 5 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="File size exceeds 5MB limit")
    
    # 3. Get the expense request
    query = select(ExpenseRequest).where(
        ExpenseRequest.id == expense_id,
        ExpenseRequest.user_id == current_user.id
    )
    result = await db.execute(query)
    expense = result.scalar_one_or_none()
    
    if not expense:
        raise HTTPException(status_code=404, detail="Expense request not found or access denied")
    
    # 4. Check status - only allow if approved or auto-approved
    if expense.status not in [ExpenseStatus.APPROVED, ExpenseStatus.AUTO_APPROVED]:
        raise HTTPException(
            status_code=400, 
            detail=f"Cannot upload payment QR. Current status is '{expense.status}'. Only approved requests can have payment QR codes."
        )

    try:
        # 5. Upload to Cloudinary (using 'payment-qr' suffix for clarity)
        upload_result = cloudinary_service.upload_receipt(
            file_content=file_content,
            filename=f"qr_{file.filename}",
            expense_id=f"PAY_{expense.request_id}"
        )
        
        # 6. Update expense
        expense.payment_qr_url = upload_result["url"]
        if payment_note:
            expense.payment_note = payment_note
            
        await db.commit()
        await db.refresh(expense)
        
        return {
            "msg": "Payment QR uploaded successfully",
            "payment_qr_url": expense.payment_qr_url,
            "payment_note": expense.payment_note
        }
        
    except Exception as e:
        await db.rollback()
        raise HTTPException(status_code=500, detail=f"Failed to upload payment QR: {str(e)}")