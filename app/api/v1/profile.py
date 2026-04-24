from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from typing import List
from app.db.session import get_db
from app.models.user import User, UserRole
from app.models.organization import Organization
from app.models.department import Department
from app.schemas.user import UserOut, UserUpdate, PasswordChange, UserCreate
from app.core.security import get_current_user
bitter_security = Depends(get_current_user)
from app.schemas.user import UserUpdateSchema
from app.core.security import get_password_hash, verify_password

from sqlalchemy.orm import joinedload
import logging

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/users", tags=["user-management"])

# --- PROFILE SECTION ---

@router.get("/me")
async def get_my_profile(
    current_user: User = bitter_security,
    db: AsyncSession = Depends(get_db)
):
    # Reload user with organization and department data
    query = (
        select(User)
        .options(joinedload(User.organization), joinedload(User.department))
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
    }

@router.post("/change-password")
async def change_password(
    data: PasswordChange, 
    db: AsyncSession = Depends(get_db), 
    current_user: User = bitter_security
):
    if not verify_password(data.current_password, current_user.hashed_password):
        raise HTTPException(status_code=400, detail="Current password incorrect")
    
    current_user.hashed_password = get_password_hash(data.new_password)
    await db.commit()
    return {"msg": "Password updated successfully"}


# --- ADMIN SECTION ---

@router.get("/approval-limit")
async def get_approval_limit(
    current_user: User = bitter_security,
    db: AsyncSession = Depends(get_db)
):
    """
    Get organization's deemed approval limit.
    
    **Access:** All authenticated users can view their organization's approval limit.
    **Note:** Only admins can update the approval limit via PATCH.
    """
    query = select(Organization).where(Organization.id == current_user.org_id)
    result = await db.execute(query)
    org = result.scalar_one_or_none()
    
    if not org:
        raise HTTPException(status_code=404, detail="Organization not found")
    
    return {
        "org_id": org.id,
        "org_name": org.name,
        "deemed_approval_limit": org.deemed_approval_limit
    }


class ApprovalLimitUpdate(BaseModel):
    deemed_approval_limit: float

@router.patch("/approval-limit")
async def update_approval_limit(
    data: ApprovalLimitUpdate,
    current_user: User = bitter_security,
    db: AsyncSession = Depends(get_db)
):
    """Update organization's deemed approval limit (Admin only)"""
    if current_user.role != UserRole.ADMIN:
        raise HTTPException(status_code=403, detail="Only admins can update approval limits")
    
    if data.deemed_approval_limit < 0:
        raise HTTPException(status_code=400, detail="Approval limit cannot be negative")
    
    query = select(Organization).where(Organization.id == current_user.org_id)
    result = await db.execute(query)
    org = result.scalar_one_or_none()
    
    if not org:
        raise HTTPException(status_code=404, detail="Organization not found")
    
    org.deemed_approval_limit = data.deemed_approval_limit
    await db.commit()
    
    return {
        "msg": "Approval limit updated successfully",
        "org_id": org.id,
        "org_name": org.name,
        "deemed_approval_limit": org.deemed_approval_limit
    }

@router.post("/add-user", response_model=UserOut)
async def add_new_user(
    user_in: UserCreate, 
    db: AsyncSession = Depends(get_db),
    current_user: User = bitter_security
):
    if current_user.role != UserRole.ADMIN:
        raise HTTPException(status_code=403, detail="Only admins can add users")
    
    # Check if user exists
    existing_user = await db.execute(select(User).where(User.email == user_in.email))
    if existing_user.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="Email already registered")

    department_id = getattr(user_in, "department_id", None)
    if department_id is not None:
        dep_query = select(Department).where(
            Department.id == department_id,
            Department.org_id == current_user.org_id,
            Department.is_active == True,
        )
        dep_result = await db.execute(dep_query)
        if not dep_result.scalar_one_or_none():
            raise HTTPException(status_code=404, detail="Department not found")

    new_user = User(
        **user_in.model_dump(exclude={"password"}),
        hashed_password=get_password_hash(user_in.password),
        org_id=current_user.org_id
    )
    db.add(new_user)
    await db.commit()
    await db.refresh(new_user)
    return new_user

@router.get("/manage-list", response_model=List[UserOut])
async def list_organization_users(
    db: AsyncSession = Depends(get_db),
    current_user: User = bitter_security
):
    if current_user.role != UserRole.ADMIN:
        raise HTTPException(status_code=403, detail="Access denied")
        
    result = await db.execute(
        select(User).where(User.org_id == current_user.org_id)
    )
    return result.scalars().all()




@router.patch("/update/{user_id}")
async def update_user(
    user_id: int, 
    user_update: UserUpdateSchema, 
    db: AsyncSession = Depends(get_db),
    current_user: User = bitter_security
):
    # 1. Fetch the user from the database
    query = select(User).where(User.id == user_id)
    result = await db.execute(query)
    db_user = result.scalar_one_or_none()

    if not db_user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, 
            detail=f"User with ID {user_id} not found"
        )
    
    # 2. Security check: Admin can update anyone in their org, users can only update themselves
    is_admin = current_user.role == UserRole.ADMIN
    is_self_update = current_user.id == user_id
    
    if not is_admin and not is_self_update:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You can only update your own profile"
        )
    
    # Ensure user belongs to same organization (for admin updates)
    if is_admin and db_user.org_id != current_user.org_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Cannot update users from other organizations"
        )


    # 2. Convert Pydantic model to a dict, EXCLUDING fields not sent in the request
    update_data = user_update.model_dump(exclude_unset=True)

    # 3. Update fields with permission checks
    # Non-admins can only update: first_name, last_name, phone_number
    # Admins can update all fields
    
    if "first_name" in update_data:
        db_user.first_name = update_data["first_name"]
    if "last_name" in update_data:
        db_user.last_name = update_data["last_name"]
    if "phone_number" in update_data:
        db_user.phone_number = update_data["phone_number"]
    
    # Only admins can update role and is_active
    if "role" in update_data:
        if not is_admin:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only admins can change user roles"
            )
        # Convert role to lowercase to match UserRole enum values
        role_value = update_data["role"].lower()
        # Validate the role exists in UserRole enum
        try:
            db_user.role = UserRole(role_value)
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid role: {update_data['role']}. Must be one of: admin, requestor, approver, accountant"
            )
    if "department_id" in update_data:
        if not is_admin:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only admins can change user department"
            )
        department_id = update_data["department_id"]
        if department_id is None:
            db_user.department_id = None
        else:
            dep_query = select(Department).where(
                Department.id == department_id,
                Department.org_id == current_user.org_id,
                Department.is_active == True,
            )
            dep_result = await db.execute(dep_query)
            if not dep_result.scalar_one_or_none():
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Department not found"
                )
            db_user.department_id = department_id
    if "is_active" in update_data:
        if not is_admin:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only admins can change user active status"
            )
        db_user.is_active = update_data["is_active"]

    # 4. Commit changes
    try:
        await db.commit()
        await db.refresh(db_user)
        
        # Return response with proper structure
        return {
            "id": db_user.id,
            "email": db_user.email,
            "first_name": db_user.first_name,
            "last_name": db_user.last_name,
            "phone_number": db_user.phone_number,
            "role": db_user.role,
            "org_id": db_user.org_id,
            "is_active": db_user.is_active
        }
    except Exception as e:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, 
            detail="Database update failed"
        )
