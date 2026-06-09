from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from app.core.roles import enforce_branch_scope, is_admin_like, is_super_admin
from app.core.security import get_current_user
from app.db.session import get_db
from app.models.branch import Branch
from app.models.user import User

router = APIRouter(prefix="/branches", tags=["branches"])

DEFAULT_BRANCHES = [
    {"name": "Head Office", "code": "HO", "address": None},
]


class BranchCreate(BaseModel):
    name: str
    code: str | None = None
    address: str | None = None


class BranchUpdate(BaseModel):
    name: str | None = None
    code: str | None = None
    address: str | None = None
    is_active: bool | None = None


def _normalize_text(value: str) -> str:
    return " ".join(value.strip().split())


async def _ensure_branch_unique(
    db: AsyncSession,
    org_id: int,
    name: str,
    code: str | None,
    exclude_id: int | None = None,
) -> None:
    result = await db.execute(select(Branch).where(Branch.org_id == org_id))
    rows = result.scalars().all()

    name_check = _normalize_text(name).lower()
    code_check = _normalize_text(code).lower() if code else None

    for row in rows:
        if exclude_id and row.id == exclude_id:
            continue
        if row.name.strip().lower() == name_check:
            raise HTTPException(status_code=400, detail="A branch with this name already exists.")
        if code_check and row.code and row.code.strip().lower() == code_check:
            raise HTTPException(status_code=400, detail="A branch with this code already exists.")


@router.get("")
async def list_branches(
    include_inactive: bool = False,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if not is_admin_like(current_user):
        raise HTTPException(status_code=403, detail="Admin access required.")

    query = select(Branch).where(Branch.org_id == current_user.org_id)

    effective_branch_id = enforce_branch_scope(current_user, None)
    if effective_branch_id is not None:
        query = query.where(Branch.id == effective_branch_id)

    if not include_inactive:
        query = query.where(Branch.is_active.is_(True))

    result = await db.execute(query.order_by(Branch.name.asc()))
    rows = result.scalars().all()

    return [
        {
            "id": b.id,
            "name": b.name,
            "code": b.code,
            "address": b.address,
            "is_active": b.is_active,
        }
        for b in rows
    ]


@router.get("/{branch_id}")
async def get_branch(
    branch_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if not is_admin_like(current_user):
        raise HTTPException(status_code=403, detail="Admin access required.")

    enforce_branch_scope(current_user, branch_id)

    result = await db.execute(
        select(Branch).where(
            Branch.id == branch_id,
            Branch.org_id == current_user.org_id,
        )
    )
    branch = result.scalar_one_or_none()
    if not branch:
        raise HTTPException(status_code=404, detail="Branch not found.")

    return {
        "id": branch.id,
        "name": branch.name,
        "code": branch.code,
        "address": branch.address,
        "is_active": branch.is_active,
    }


@router.post("")
async def create_branch(
    payload: BranchCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if not is_super_admin(current_user):
        raise HTTPException(status_code=403, detail="Only super admins can create branches.")

    name = _normalize_text(payload.name)
    if len(name) < 2:
        raise HTTPException(status_code=400, detail="Branch name must have at least 2 characters")

    code = _normalize_text(payload.code) if payload.code else None
    address = _normalize_text(payload.address) if payload.address else None

    await _ensure_branch_unique(db, current_user.org_id, name=name, code=code)

    branch = Branch(
        org_id=current_user.org_id,
        name=name,
        code=code,
        address=address,
        is_active=True,
    )
    db.add(branch)
    await db.commit()
    await db.refresh(branch)

    return {
        "id": branch.id,
        "name": branch.name,
        "code": branch.code,
        "address": branch.address,
        "is_active": branch.is_active,
    }


@router.patch("/{branch_id}")
async def update_branch(
    branch_id: int,
    payload: BranchUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if not is_super_admin(current_user):
        raise HTTPException(status_code=403, detail="Only super admins can update branches.")

    result = await db.execute(
        select(Branch).where(
            Branch.id == branch_id,
            Branch.org_id == current_user.org_id,
        )
    )
    branch = result.scalar_one_or_none()
    if not branch:
        raise HTTPException(status_code=404, detail="Branch not found.")

    new_name = _normalize_text(payload.name) if payload.name is not None else branch.name
    new_code = _normalize_text(payload.code) if payload.code is not None else branch.code
    new_address = _normalize_text(payload.address) if payload.address is not None else branch.address

    if len(new_name) < 2:
        raise HTTPException(status_code=400, detail="Branch name must have at least 2 characters")

    await _ensure_branch_unique(
        db,
        current_user.org_id,
        name=new_name,
        code=new_code,
        exclude_id=branch.id,
    )

    branch.name = new_name
    branch.code = new_code
    branch.address = new_address
    if payload.is_active is not None:
        branch.is_active = payload.is_active

    await db.commit()
    await db.refresh(branch)

    return {
        "id": branch.id,
        "name": branch.name,
        "code": branch.code,
        "address": branch.address,
        "is_active": branch.is_active,
    }


@router.delete("/{branch_id}")
async def delete_branch(
    branch_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if not is_super_admin(current_user):
        raise HTTPException(status_code=403, detail="Only super admins can delete branches.")

    result = await db.execute(
        select(Branch).where(
            Branch.id == branch_id,
            Branch.org_id == current_user.org_id,
        )
    )
    branch = result.scalar_one_or_none()
    if not branch:
        raise HTTPException(status_code=404, detail="Branch not found.")

    branch.is_active = False
    await db.commit()

    return {"message": "Branch deactivated successfully"}


@router.post("/seed-defaults")
async def seed_default_branches(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if not is_super_admin(current_user):
        raise HTTPException(status_code=403, detail="Only super admins can seed branches.")

    result = await db.execute(select(Branch).where(Branch.org_id == current_user.org_id))
    existing = result.scalars().all()
    existing_names = {row.name.strip().lower() for row in existing}
    existing_codes = {row.code.strip().lower() for row in existing if row.code}

    created = []
    skipped = []

    for item in DEFAULT_BRANCHES:
        name = item["name"]
        code = item["code"]
        if name.strip().lower() in existing_names or (code and code.strip().lower() in existing_codes):
            skipped.append(name)
            continue

        row = Branch(
            org_id=current_user.org_id,
            name=name,
            code=code,
            address=item.get("address"),
            is_active=True,
        )
        db.add(row)
        created.append(name)

    await db.commit()

    return {
        "message": "Seeded defaults",
        "created": created,
        "skipped": skipped,
    }
