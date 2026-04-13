from __future__ import annotations
from pydantic import BaseModel, EmailStr, field_validator
from typing import Optional
from app.models.user import UserRole

# Shared properties
class UserBase(BaseModel):
    email: EmailStr
    first_name: str
    last_name: str
    phone_number: Optional[str] = None

# Properties to receive via API on creation
class UserCreate(UserBase):
    password: str
    org_id: int
    role: UserRole = UserRole.REQUESTOR

# Properties to return via API
class UserOut(UserBase):
    id: int
    role: UserRole
    org_id: int
    is_active: bool

    class Config:
        from_attributes = True

class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"

class UserUpdate(BaseModel):
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    phone_number: Optional[str] = None
    role: Optional[UserRole] = None
    is_active: Optional[bool] = None

class PasswordChange(BaseModel):
    current_password: str
    new_password: str
    
    @field_validator('new_password')
    @classmethod
    def validate_password(cls, v):
        errors = []
        
        if len(v) < 8:
            errors.append('at least 8 characters')
        if not any(c.isupper() for c in v):
            errors.append('one uppercase letter')
        if not any(c.islower() for c in v):
            errors.append('one lowercase letter')
        if not any(c.isdigit() for c in v):
            errors.append('one number')
        if not any(c in '!@#$%^&*()_+-=[]{}|;:,.<>?' for c in v):
            errors.append('one special character (!@#$%^&*()_+-=[]{}|;:,.<>?)')
        
        if errors:
            raise ValueError(f"Password must contain: {', '.join(errors)}")
        return v

class ForgotPasswordRequest(BaseModel):
    email: EmailStr

from pydantic import BaseModel, EmailStr

class OTPVerifyRequest(BaseModel):
    email: EmailStr
    otp: str

class PasswordResetRequest(BaseModel):
    email: EmailStr
    otp: str
    new_password: str
    
    @field_validator('new_password')
    @classmethod
    def validate_password(cls, v):
        errors = []
        
        if len(v) < 8:
            errors.append('at least 8 characters')
        if not any(c.isupper() for c in v):
            errors.append('one uppercase letter')
        if not any(c.islower() for c in v):
            errors.append('one lowercase letter')
        if not any(c.isdigit() for c in v):
            errors.append('one number')
        if not any(c in '!@#$%^&*()_+-=[]{}|;:,.<>?' for c in v):
            errors.append('one special character (!@#$%^&*()_+-=[]{}|;:,.<>?)')
        
        if errors:
            raise ValueError(f"Password must contain: {', '.join(errors)}")
        return v

class LoginRequest(BaseModel):
    email: EmailStr
    password: str

from pydantic import BaseModel, EmailStr
from typing import Optional

class OrgInfo(BaseModel):
    id: int
    name: str
    org_code: str

class LoginResponse(BaseModel):
    access_token: str
    token_type: str
    email: EmailStr
    first_name: str
    last_name: str
    phone_number: Optional[str]
    role: str
    organization: OrgInfo  # Nested organization data

class UserCreateByAdmin(BaseModel):
    email: EmailStr
    first_name: str
    last_name: str
    phone_number: str
    role: str  # REQUESTOR or ACCOUNTANT

 # Add this at the very top
from pydantic import BaseModel, EmailStr
from datetime import datetime
from typing import Optional

class UserListOut(BaseModel):
    id: int
    first_name: str
    last_name: str
    email: EmailStr
    role: str
    phone_number: Optional[str]
    is_active: bool
    org_id: int
    created_at: datetime

    class Config:
        from_attributes = True

# Explicitly tell Pydantic to "rebuild" the model to clear the error
UserListOut.model_rebuild()

from pydantic import BaseModel, EmailStr
from typing import Optional


class UserUpdateSchema(BaseModel):
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    phone_number: Optional[str] = None
    role: Optional[str] = None
    is_active: Optional[bool] = None

# Important for Python 3.14
UserUpdateSchema.model_rebuild()