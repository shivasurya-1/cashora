from fastapi import APIRouter, Depends, HTTPException, status, BackgroundTasks
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from app.db.session import get_db
from app.models.user import User, UserRole
from app.models.organization import Organization
from app.models.department import Department
from app.models.branch import Branch
from app.schemas.user import UserCreate, UserOut, Token
from app.schemas.organization import OrganizationSetup  
from app.core.security import get_password_hash, verify_password, create_access_token
from fastapi.security import OAuth2PasswordRequestForm
import secrets
from datetime import datetime, timedelta
from fastapi import BackgroundTasks
from app.schemas.user import ForgotPasswordRequest
from app.schemas.user import OTPVerifyRequest, UserCreateByAdmin
from app.core.roles import can_assign_role, enforce_branch_scope, is_admin_like

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

    # 3. Create owner user (org highest role is admin)
    admin_user = User(
        email=org_in.admin_details.email,
        hashed_password=get_password_hash(temp_password), # Hash the random password
        first_name=org_in.admin_details.first_name,
        last_name=org_in.admin_details.last_name,
        phone_number=org_in.admin_details.phone_number,
        role=UserRole.ADMIN,
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

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account disabled"
        )

    if str(user.role).lower() != "app_owner" and user.organization and not getattr(user.organization, "is_active", True):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Organization disabled"
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
    if not is_admin_like(current_admin):
        raise HTTPException(status_code=403, detail="Admin access required")

    # 2. Generate Credentials
    temp_password = generate_random_password()

    normalized_role = (user_in.role or "").strip().lower()
    if not can_assign_role(str(current_admin.role), normalized_role):
        raise HTTPException(status_code=403, detail="You are not allowed to assign this role")

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

    effective_branch_id = enforce_branch_scope(current_admin, user_in.branch_id)
    if effective_branch_id is not None:
        branch_query = select(Branch).where(
            Branch.id == effective_branch_id,
            Branch.org_id == current_admin.org_id,
            Branch.is_active.is_(True),
        )
        branch_result = await db.execute(branch_query)
        if not branch_result.scalar_one_or_none():
            raise HTTPException(status_code=404, detail="Branch not found")
    
    # 3. Create User linked to the Admin's Org
    try:
        parsed_role = UserRole(normalized_role)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid role. Allowed: admin, requestor, accountant")

    new_user = User(
        email=user_in.email,
        hashed_password=get_password_hash(temp_password),
        first_name=user_in.first_name,
        last_name=user_in.last_name,
        phone_number=user_in.phone_number,
        role=parsed_role,
        org_id=current_admin.org_id, # AUTO-LINK to same organization
        department_id=department_id,
        branch_id=effective_branch_id,
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
from sqlalchemy.orm import joinedload as _joinedload2

@router.get("/me")
async def get_current_user_info(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Validate JWT and return the current user's profile. Called by Flutter on startup."""
    query = (
        select(User)
        .options(_joinedload2(User.organization), _joinedload2(User.department), _joinedload2(User.branch))
        .where(User.id == current_user.id)
    )
    result = await db.execute(query)
    user_with_org = result.scalar_one()

    return {
        "id": user_with_org.id,
        "email": user_with_org.email,
        "first_name": user_with_org.first_name,
        "last_name": user_with_org.last_name,
        "phone_number": user_with_org.phone_number,
        "role": user_with_org.role,
        "org_id": user_with_org.org_id,
        "is_active": user_with_org.is_active,
        "org_code": user_with_org.organization.org_code,
        "org_name": user_with_org.organization.name,
        "department_id": user_with_org.department.id if user_with_org.department else None,
        "department_name": user_with_org.department.name if user_with_org.department else None,
        "department_code": user_with_org.department.code if user_with_org.department else None,
        "branch_id": user_with_org.branch.id if user_with_org.branch else None,
        "branch_name": user_with_org.branch.name if user_with_org.branch else None,
        "branch_code": user_with_org.branch.code if user_with_org.branch else None,
    }


@router.post("/logout")
async def logout(current_user: User = Depends(get_current_user)):
    """Stateless JWT logout. Flutter removes the token client-side."""
    return {"msg": "Logged out successfully"}


@router.get("/users")
async def get_org_users(
    branch_id: int | None = None,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    # 🛡️ SECURITY GATE: Only allow admin/super admin role
    if not is_admin_like(current_user):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, 
            detail="Access Denied: Only Admins can view the organization staff list."
        )

    effective_branch_id = enforce_branch_scope(current_user, branch_id)

    # 🏢 MULTI-TENANCY: Only fetch users from the Admin's own organization
    print(f"DEBUG: Fetching users for org_id: {current_user.org_id}")
    query = (
        select(User)
        .options(_joinedload2(User.department), _joinedload2(User.branch))
        .where(User.org_id == current_user.org_id)
        .order_by(User.created_at.desc())
    )
    if effective_branch_id is not None:
        query = query.where(User.branch_id == effective_branch_id)

    result = await db.execute(query)
    users = result.scalars().all()
    
    print(f"DEBUG: Found {len(users)} users for org_id {current_user.org_id}")
    for user in users:
        print(f"  - User: {user.email}, org_id: {user.org_id}")

    return [
        {
            "id": user.id,
            "first_name": user.first_name,
            "last_name": user.last_name,
            "email": user.email,
            "role": user.role,
            "department_id": user.department_id,
            "department_name": user.department.name if user.department else None,
            "branch_id": user.branch_id,
            "branch_name": user.branch.name if user.branch else None,
            "phone_number": user.phone_number,
            "is_active": user.is_active,
            "org_id": user.org_id,
            "created_at": user.created_at,
        }
        for user in users
    ]