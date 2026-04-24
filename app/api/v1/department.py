from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy import func

from app.db.session import get_db
from app.models.department import Department
from app.models.user import User, UserRole
from app.core.security import get_current_user


router = APIRouter(prefix="/departments", tags=["departments"])


DEFAULT_DEPARTMENTS = [
    {"name": "Finance", "code": "FIN"},
    {"name": "Human Resources", "code": "HR"},
    {"name": "Operations", "code": "OPS"},
    {"name": "Information Technology", "code": "IT"},
]


class DepartmentCreate(BaseModel):
    name: str
    code: str | None = None


class DepartmentUpdate(BaseModel):
    name: str | None = None
    code: str | None = None
    is_active: bool | None = None


def _normalize_text(value: str) -> str:
    return " ".join(value.strip().split())


async def _ensure_department_unique(
    db: AsyncSession,
    org_id: int,
    name: str,
    code: str | None,
    exclude_id: int | None = None,
) -> None:
    name_check = _normalize_text(name).lower()

    name_query = select(Department).where(Department.org_id == org_id)
    name_result = await db.execute(name_query)
    rows = name_result.scalars().all()

    for row in rows:
        if exclude_id and row.id == exclude_id:
            continue
        if row.name.strip().lower() == name_check:
            raise HTTPException(status_code=400, detail="Department name already exists in organization")
        if code and row.code and row.code.strip().lower() == code.strip().lower():
            raise HTTPException(status_code=400, detail="Department code already exists in organization")


@router.post("")
async def create_department(
    payload: DepartmentCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if current_user.role != UserRole.ADMIN:
        raise HTTPException(status_code=403, detail="Only admins can create departments")

    name = _normalize_text(payload.name)
    if len(name) < 2:
        raise HTTPException(status_code=400, detail="Department name must have at least 2 characters")

    code = _normalize_text(payload.code) if payload.code else None
    await _ensure_department_unique(db, current_user.org_id, name=name, code=code)

    department = Department(
        org_id=current_user.org_id,
        name=name,
        code=code,
        is_active=True,
    )
    db.add(department)
    await db.commit()
    await db.refresh(department)

    return {
        "id": department.id,
        "name": department.name,
        "code": department.code,
        "is_active": department.is_active,
    }


@router.get("")
async def list_departments(
    include_inactive: bool = False,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    base_query = select(Department).where(Department.org_id == current_user.org_id)
    if not include_inactive:
        base_query = base_query.where(Department.is_active == True)

    result = await db.execute(base_query.order_by(Department.name.asc()))
    departments = result.scalars().all()

    return [
        {
            "id": d.id,
            "name": d.name,
            "code": d.code,
            "is_active": d.is_active,
        }
        for d in departments
    ]


@router.get("/{department_id}")
async def get_department(
    department_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    query = select(Department).where(
        Department.id == department_id,
        Department.org_id == current_user.org_id,
    )
    result = await db.execute(query)
    department = result.scalar_one_or_none()
    if not department:
        raise HTTPException(status_code=404, detail="Department not found")

    return {
        "id": department.id,
        "name": department.name,
        "code": department.code,
        "is_active": department.is_active,
    }


@router.patch("/{department_id}")
async def update_department(
    department_id: int,
    payload: DepartmentUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if current_user.role != UserRole.ADMIN:
        raise HTTPException(status_code=403, detail="Only admins can update departments")

    query = select(Department).where(
        Department.id == department_id,
        Department.org_id == current_user.org_id,
    )
    result = await db.execute(query)
    department = result.scalar_one_or_none()
    if not department:
        raise HTTPException(status_code=404, detail="Department not found")

    new_name = _normalize_text(payload.name) if payload.name is not None else department.name
    new_code = _normalize_text(payload.code) if payload.code is not None else department.code

    if len(new_name) < 2:
        raise HTTPException(status_code=400, detail="Department name must have at least 2 characters")

    await _ensure_department_unique(
        db,
        current_user.org_id,
        name=new_name,
        code=new_code,
        exclude_id=department.id,
    )

    department.name = new_name
    department.code = new_code
    if payload.is_active is not None:
        department.is_active = payload.is_active

    await db.commit()
    await db.refresh(department)

    return {
        "id": department.id,
        "name": department.name,
        "code": department.code,
        "is_active": department.is_active,
    }


@router.delete("/{department_id}")
async def delete_department(
    department_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if current_user.role != UserRole.ADMIN:
        raise HTTPException(status_code=403, detail="Only admins can delete departments")

    query = select(Department).where(
        Department.id == department_id,
        Department.org_id == current_user.org_id,
    )
    result = await db.execute(query)
    department = result.scalar_one_or_none()
    if not department:
        raise HTTPException(status_code=404, detail="Department not found")

    department.is_active = False
    await db.commit()

    return {"message": "Department deactivated successfully"}


@router.get("/{department_id}/users")
async def list_department_users(
    department_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    query = select(Department).where(
        Department.id == department_id,
        Department.org_id == current_user.org_id,
    )
    dep_result = await db.execute(query)
    department = dep_result.scalar_one_or_none()
    if not department:
        raise HTTPException(status_code=404, detail="Department not found")

    users_query = select(User).where(
        User.org_id == current_user.org_id,
        User.department_id == department_id,
        User.is_active == True,
    ).order_by(User.first_name.asc())
    users_result = await db.execute(users_query)
    users = users_result.scalars().all()

    return {
        "department": {
            "id": department.id,
            "name": department.name,
            "code": department.code,
        },
        "users": [
            {
                "id": u.id,
                "first_name": u.first_name,
                "last_name": u.last_name,
                "email": u.email,
                "role": u.role,
            }
            for u in users
        ],
    }


@router.post("/seed-defaults")
async def seed_default_departments(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if current_user.role != UserRole.ADMIN:
        raise HTTPException(status_code=403, detail="Only admins can seed departments")

    existing_query = select(Department).where(Department.org_id == current_user.org_id)
    existing_result = await db.execute(existing_query)
    existing = existing_result.scalars().all()

    existing_names = {row.name.strip().lower() for row in existing}
    existing_codes = {row.code.strip().lower() for row in existing if row.code}

    created = []
    skipped = []

    for item in DEFAULT_DEPARTMENTS:
        name = item["name"]
        code = item["code"]
        if name.strip().lower() in existing_names or code.strip().lower() in existing_codes:
            skipped.append(name)
            continue

        row = Department(
            org_id=current_user.org_id,
            name=name,
            code=code,
            is_active=True,
        )
        db.add(row)
        created.append(name)

    await db.commit()

    return {
        "message": "Default departments processed",
        "created": created,
        "skipped": skipped,
    }
