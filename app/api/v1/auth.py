from fastapi import APIRouter, Depends, HTTPException, status, BackgroundTasks
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from app.db.session import get_db
from app.models.user import User, UserRole
from app.models.organization import Organization
from app.models.department import Department
from app.schemas.user import UserCreate, UserOut, Token
from app.schemas.organization import OrganizationSetup  
from app.core.security import get_password_hash, verify_password, create_access_token
from fastapi.security import OAuth2PasswordRequestForm
import secrets
from datetime import datetime, timedelta
from fastapi import BackgroundTasks
from app.schemas.user import ForgotPasswordRequest
from app.schemas.user import OTPVerifyRequest, UserCreateByAdmin

# Utilities and Services
from app.utils.codes import generate_org_code, generate_random_password
from app.services.mail_service import send_welcome_email,send_otp_email

router = APIRouter(prefix="/auth", tags=["authentication"])

# In-memory OTP storage (For production, use Redis)
# Format: {email: {"otp": "123456", "expires_at": datetime}}
otp_storage = {}

@router.post("/setup-organization", response_model=UserOut)
async def setup_organization(
    org_in: OrganizationSetup, 
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db)
):
    # 1. Generate unique identifiers
    unique_org_code = generate_org_code()
    temp_password = generate_random_password()
    
    # 2. Create Organization
    new_org = Organization(
        name=org_in.org_name, 
        org_code=unique_org_code
    )
    db.add(new_org)
    await db.flush() 

    # 3. Create Admin User (Backend forces role=ADMIN)
    admin_user = User(
        email=org_in.admin_details.email,
        hashed_password=get_password_hash(temp_password), # Hash the random password
        first_name=org_in.admin_details.first_name,
        last_name=org_in.admin_details.last_name,
        phone_number=org_in.admin_details.phone_number,
        role=UserRole.ADMIN, # Forced by backend
        org_id=new_org.id
    )
    db.add(admin_user)
    
    try:
        await db.commit()
        await db.refresh(admin_user)
        
        # 4. Trigger Enhanced Email Task
        background_tasks.add_task(
            send_welcome_email, 
            email=admin_user.email, 
            org_code=unique_org_code, 
            temp_password=temp_password, # Send the plain text password ONLY once via email
            name=f"{admin_user.first_name} {admin_user.last_name}"
        )
        
        return admin_user
    except Exception as e:
        await db.rollback()
        raise HTTPException(status_code=500, detail=str(e))
# ... (Keep your /login and get_current_user logic below this)

from app.schemas.user import LoginRequest,LoginResponse
from sqlalchemy.orm import joinedload

@router.post("/login", response_model=LoginResponse)
async def login(
    data: LoginRequest, 
    db: AsyncSession = Depends(get_db)
):
    # Join the Organization table during the user lookup
    query = (
        select(User)
        .options(joinedload(User.organization)) 
        .where(User.email == data.email)
    )
    result = await db.execute(query)
    user = result.scalar_one_or_none()
    
    if not user or not verify_password(data.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, 
            detail="Invalid email or password"
        )
        
    access_token = create_access_token(subject=user.id)
    
    return {
        "access_token": access_token,
        "token_type": "bearer",
        "email": user.email,
        "first_name": user.first_name,
        "last_name": user.last_name,
        "phone_number": user.phone_number,
        "role": user.role,
        "organization": {
            "id": user.organization.id,
            "name": user.organization.name,
            "org_code": user.organization.org_code
        }
    }

@router.post("/forgot-password")
async def forgot_password(
    data: ForgotPasswordRequest, 
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db)
):
    # 1. Verify user exists
    query = select(User).where(User.email == data.email)
    result = await db.execute(query)
    user = result.scalar_one_or_none()
    
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Email address not found. Please check and try again."
        )

    # 2. Generate 6-digit OTP
    otp = "".join([str(secrets.randbelow(10)) for _ in range(6)])

    # 3. Store OTP with expiration (5 minutes)
    otp_storage[data.email] = {
        "otp": otp,
        "expires_at": datetime.utcnow() + timedelta(minutes=5)
    } 
    print(f"DEBUG: Generated OTP for {data.email} is {otp}")

    # 4. Trigger mail_service (Background Task)
    background_tasks.add_task(
        send_otp_email, # You need to create this in mail_service.py
        email=data.email, 
        otp=otp
    )

    return {"msg": "OTP sent to registered email"}



@router.post("/verify-otp")
async def verify_otp(data: OTPVerifyRequest):
    # 1. Check if OTP exists for this email
    if data.email not in otp_storage:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No OTP request found for this email. Please request a new OTP."
        )
    
    stored_data = otp_storage[data.email]
    
    # 2. Check if OTP has expired
    if datetime.utcnow() > stored_data["expires_at"]:
        # Clean up expired OTP
        del otp_storage[data.email]
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="OTP has expired. Please request a new OTP."
        )
    
    # 3. Verify the OTP matches
    if data.otp != stored_data["otp"]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid OTP. Please check and try again."
        )
    
    # 4. OTP is valid - mark it as verified (optional: you can add a verified flag)
    # For now, we keep it in storage so reset-password can verify the user went through OTP flow
    otp_storage[data.email]["verified"] = True
    
    return {"msg": "OTP verified successfully. You may now reset your password."}

from app.schemas.user import PasswordResetRequest

@router.post("/reset-password")
async def reset_password(data: PasswordResetRequest, db: AsyncSession = Depends(get_db)):
    # 1. Verify that OTP was verified for this email
    if data.email not in otp_storage:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Please verify OTP before resetting password."
        )
    
    if not otp_storage[data.email].get("verified", False):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="OTP not verified. Please verify OTP first."
        )
    
    # 2. Find the user
    query = select(User).where(User.email == data.email)
    result = await db.execute(query)
    user = result.scalar_one_or_none()

    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    # 3. Hash and Update the new password
    user.hashed_password = get_password_hash(data.new_password)
    
    try:
        await db.commit()
        # Clean up OTP after successful password reset
        if data.email in otp_storage:
            del otp_storage[data.email]
        return {"msg": "Password has been reset successfully. You can now login."}
    except Exception as e:
        await db.rollback()
        raise HTTPException(status_code=500, detail="Failed to update password")

from app.core.security import get_current_user # Dependency to get logged-in user


@router.post("/add-staff", response_model=UserOut)
async def add_staff(
    user_in: UserCreateByAdmin,
    background_tasks: BackgroundTasks,
    current_admin: User = Depends(get_current_user), # Only logged-in users
    db: AsyncSession = Depends(get_db)
):
    # 1. Security Check: Only Admins can add staff
    if current_admin.role != UserRole.ADMIN:
        raise HTTPException(status_code=403, detail="Only Admins can add staff members")

    # 2. Generate Credentials
    temp_password = generate_random_password()

    department_id = user_in.department_id
    if department_id is not None:
        dep_query = select(Department).where(
            Department.id == department_id,
            Department.org_id == current_admin.org_id,
            Department.is_active == True,
        )
        dep_result = await db.execute(dep_query)
        department = dep_result.scalar_one_or_none()
        if not department:
            raise HTTPException(status_code=404, detail="Department not found")
    
    # 3. Create User linked to the Admin's Org
    try:
        parsed_role = UserRole(user_in.role.lower())
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid role. Allowed: admin, requestor, approver, accountant")

    new_user = User(
        email=user_in.email,
        hashed_password=get_password_hash(temp_password),
        first_name=user_in.first_name,
        last_name=user_in.last_name,
        phone_number=user_in.phone_number,
        role=parsed_role,
        org_id=current_admin.org_id, # AUTO-LINK to same organization
        department_id=department_id,
        is_active=True
    )
    
    db.add(new_user)
    
    try:
        await db.commit()
        await db.refresh(new_user)

        # 4. Fetch Org Code for the email
        query = select(Organization).where(Organization.id == current_admin.org_id)
        org_result = await db.execute(query)
        org = org_result.scalar_one()

        # 5. Notify the new staff member via email
        background_tasks.add_task(
            send_welcome_email, 
            email=new_user.email,
            org_code=org.org_code,
            temp_password=temp_password,
            name=f"{new_user.first_name} {new_user.last_name}"
        )

        return new_user
    except Exception as e:
        await db.rollback()
        raise HTTPException(status_code=400, detail="User already exists")

from typing import List
from app.schemas.user import UserListOut

@router.get("/users", response_model=list[UserListOut])
async def get_org_users(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    # 🛡️ SECURITY GATE: Only allow ADMIN role
    if current_user.role != UserRole.ADMIN:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, 
            detail="Access Denied: Only Admins can view the organization staff list."
        )

    # 🏢 MULTI-TENANCY: Only fetch users from the Admin's own organization
    print(f"DEBUG: Fetching users for org_id: {current_user.org_id}")
    query = (
        select(User)
        .where(User.org_id == current_user.org_id)
        .order_by(User.created_at.desc())
    )
    result = await db.execute(query)
    users = result.scalars().all()
    
    print(f"DEBUG: Found {len(users)} users for org_id {current_user.org_id}")
    for user in users:
        print(f"  - User: {user.email}, org_id: {user.org_id}")

    return users