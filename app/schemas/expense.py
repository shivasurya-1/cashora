from pydantic import BaseModel
from typing import Optional, List
from app.models.expense import ExpenseStatus, ExpenseCategory, ExpenseRequestType, PaymentMethod
from datetime import datetime

# --- Existing Requestor Schemas ---

class ExpenseCreate(BaseModel):
    request_type: ExpenseRequestType = ExpenseRequestType.PRE_APPROVED
    amount: float
    purpose: str
    description: Optional[str] = None
    category: ExpenseCategory
    receipt_url: Optional[str] = None
    payment_qr_url: Optional[str] = None
    payment_note: Optional[str] = None

# --- Requestor Info Schema ---

class RequestorInfo(BaseModel):
    first_name: str
    last_name: str
    email: str

    class Config:
        from_attributes = True

# --- Missing Approver Schemas ---

class ClarificationCreate(BaseModel):
    question: str

class ClarificationOut(BaseModel):
    id: int
    expense_id: int
    question: str
    response: Optional[str] = None
    asked_at: datetime
    responded_at: Optional[datetime] = None

    class Config:
        from_attributes = True

class ExpenseOut(BaseModel):
    id: int
    request_id: str
    request_type: ExpenseRequestType
    amount: float
    purpose: str
    description: Optional[str] = None
    category: ExpenseCategory
    receipt_url: Optional[str] = None
    payment_qr_url: Optional[str] = None
    payment_note: Optional[str] = None
    payment_method: Optional[PaymentMethod] = None
    transaction_reference: Optional[str] = None
    status: ExpenseStatus
    created_at: datetime
    clarifications: List[ClarificationOut] = []
    requestor: RequestorInfo

    class Config:
        from_attributes = True


class ApproverInfo(BaseModel):
    id: int
    first_name: str
    last_name: str

    class Config:
        from_attributes = True


class AccountantExpenseOut(ExpenseOut):
    approver: Optional[ApproverInfo] = None

    class Config:
        from_attributes = True


class PaginatedExpenses(BaseModel):
    total: int
    page: int
    size: int
    items: List[AccountantExpenseOut]