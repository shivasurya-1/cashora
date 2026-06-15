from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from typing import List
from app.db.session import get_db
from app.models.user import User, UserRole
from app.models.organization import Organization
from app.models.department import Department
from app.models.branch import Branch
from app.schemas.user import UserOut, UserUpdate, PasswordChange, UserCreate
from app.core.security import get_current_user
from app.core.roles import can_assign_role, enforce_branch_scope, is_admin_like, is_branch_admin
bitter_security = Depends(get_current_user)
from app.schemas.user import UserUpdateSchema
from app.core.security import get_password_hash, verify_password

from sqlalchemy.orm import joinedload
import logging
from sqlalchemy import func

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
        .options(joinedload(User.organization), joinedload(User.department), joinedload(User.branch))
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
    if not is_admin_like(current_user):
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
    if not is_admin_like(current_user):
        raise HTTPException(status_code=403, detail="Only admins can add users")

    normalized_role = str(user_in.role).lower() if getattr(user_in, "role", None) else UserRole.REQUESTOR.value
    if not can_assign_role(str(current_user.role), normalized_role):
        raise HTTPException(status_code=403, detail="You are not allowed to assign this role")
    
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

    branch_id = getattr(user_in, "branch_id", None)
    effective_branch_id = enforce_branch_scope(current_user, branch_id)
    if effective_branch_id is not None:
        branch_query = select(Branch).where(
            Branch.id == effective_branch_id,
            Branch.org_id == current_user.org_id,
            Branch.is_active.is_(True),
        )
        branch_result = await db.execute(branch_query)
        if not branch_result.scalar_one_or_none():
            raise HTTPException(status_code=404, detail="Branch not found")

    new_user = User(
        **user_in.model_dump(exclude={"password"}),
        hashed_password=get_password_hash(user_in.password),
        org_id=current_user.org_id,
        branch_id=effective_branch_id,
    )
    new_user.role = normalized_role
    db.add(new_user)
    await db.commit()
    await db.refresh(new_user)
    return new_user

@router.get("/manage-list", response_model=List[UserOut])
async def list_organization_users(
    branch_id: int | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = bitter_security
):
    if not is_admin_like(current_user):
        raise HTTPException(status_code=403, detail="Access denied")

    effective_branch_id = enforce_branch_scope(current_user, branch_id)
        
    query = select(User).where(User.org_id == current_user.org_id)
    if effective_branch_id is not None:
        query = query.where(User.branch_id == effective_branch_id)

    result = await db.execute(query)
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
    is_admin = is_admin_like(current_user)
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

    original_role = str(db_user.role)

    if is_branch_admin(current_user):
        if db_user.branch_id != current_user.branch_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Branch-scoped admin can only update users in their branch"
            )


    # 2. Convert Pydantic model to a dict, EXCLUDING fields not sent in the request
    update_data = user_update.model_dump(exclude_unset=True)

    # Reject email changes — email is immutable via this endpoint
    if "email" in update_data:
        raise HTTPException(
            status_code=400,
            detail="Email cannot be changed. Contact your organisation admin."
        )

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

        role_value = update_data["role"].lower()

        if not can_assign_role(str(current_user.role), role_value):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You are not allowed to assign this role"
            )

        try:
            UserRole(role_value)
            db_user.role = role_value
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid role: {update_data['role']}. Must be one of: admin, requestor, accountant"
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
    if "branch_id" in update_data:
        if not is_admin:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only admins can change user branch"
            )

        branch_id = enforce_branch_scope(current_user, update_data["branch_id"])
        if branch_id is None:
            db_user.branch_id = None
        else:
            branch_query = select(Branch).where(
                Branch.id == branch_id,
                Branch.org_id == current_user.org_id,
                Branch.is_active.is_(True),
            )
            branch_result = await db.execute(branch_query)
            if not branch_result.scalar_one_or_none():
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Branch not found"
                )
            db_user.branch_id = branch_id
    if "is_active" in update_data:
        if not is_admin:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only admins can change user active status"
            )
        db_user.is_active = update_data["is_active"]

    target_role = str(update_data.get("role", original_role))
    target_active = update_data.get("is_active", db_user.is_active)
    demoting_owner = original_role in {UserRole.SUPER_ADMIN.value, UserRole.ADMIN.value} and target_role not in {UserRole.SUPER_ADMIN.value, UserRole.ADMIN.value}
    deactivating_owner = original_role in {UserRole.SUPER_ADMIN.value, UserRole.ADMIN.value} and target_active is False
    if demoting_owner or deactivating_owner:
        owner_count_result = await db.execute(
            select(func.count(User.id)).where(
                User.org_id == current_user.org_id,
                User.role.in_([UserRole.SUPER_ADMIN.value, UserRole.ADMIN.value]),
                User.is_active.is_(True),
            )
        )
        owner_count = int(owner_count_result.scalar() or 0)
        if owner_count <= 1:
            raise HTTPException(status_code=409, detail="Cannot remove the last owner.")

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
