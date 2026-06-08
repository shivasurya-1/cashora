from pydantic import BaseModel, computed_field
from typing import Optional, List
from app.models.expense import ExpenseStatus, ExpenseRequestType, PaymentMethod
from datetime import datetime

# --- Existing Requestor Schemas ---

class ExpenseCreate(BaseModel):
    request_type: ExpenseRequestType = ExpenseRequestType.PRE_APPROVED
    amount: float
    purpose: str
    description: Optional[str] = None
    category: str
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
    category: str
    receipt_url: Optional[str] = None
    payment_qr_url: Optional[str] = None
    payment_note: Optional[str] = None
    payment_method: Optional[PaymentMethod] = None
    transaction_reference: Optional[str] = None
    status: ExpenseStatus
    created_at: datetime
    approved_at: Optional[datetime] = None
    rejected_at: Optional[datetime] = None
    paid_at: Optional[datetime] = None
    clarifications: List[ClarificationOut] = []
    requestor: RequestorInfo

    @computed_field
    @property
    def requestor_name(self) -> str:
        if self.requestor:
            return f"{self.requestor.first_name} {self.requestor.last_name}".strip()
        return ""

    @computed_field
    @property
    def requestor_email(self) -> str:
        if self.requestor:
            return self.requestor.email or ""
        return ""

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