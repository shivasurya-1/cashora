from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
import re

from app.db.session import get_db
from app.models.category import Category
from app.models.user import User, UserRole
from app.core.security import get_current_user

router = APIRouter(prefix="/categories", tags=["categories"])

DEFAULT_CATEGORIES = [
    {"name": "Travel", "slug": "travel"},
    {"name": "Meals", "slug": "meals"},
    {"name": "Software", "slug": "software"},
    {"name": "Office Supplies", "slug": "office_supplies"},
    {"name": "Transport", "slug": "transport"},
    {"name": "Accommodation", "slug": "accommodation"},
    {"name": "Entertainment", "slug": "entertainment"},
    {"name": "Others", "slug": "others"},
]


class CategoryCreate(BaseModel):
    name: str
    code: str | None = None


class CategoryUpdate(BaseModel):
    name: str | None = None
    code: str | None = None
    is_active: bool | None = None


def _normalize_text(value: str) -> str:
    return " ".join(value.strip().split())


def _slugify(value: str) -> str:
    normalized = _normalize_text(value).lower()
    normalized = re.sub(r"\s*&\s*", "_", normalized)
    normalized = normalized.replace(" ", "_")
    normalized = re.sub(r"_+", "_", normalized)
    return normalized.strip("_")


async def _ensure_category_unique(
    db: AsyncSession,
    org_id: int,
    name: str,
    slug: str,
    code: str | None,
    exclude_id: int | None = None,
) -> None:
    query = select(Category).where(Category.org_id == org_id)
    result = await db.execute(query)
    rows = result.scalars().all()

    name_check = name.strip().lower()
    slug_check = slug.strip().lower()
    code_check = code.strip().lower() if code else None

    for row in rows:
        if exclude_id and row.id == exclude_id:
            continue
        if row.name.strip().lower() == name_check:
            raise HTTPException(status_code=400, detail="Category name already exists in organization")
        if row.slug.strip().lower() == slug_check:
            raise HTTPException(status_code=400, detail="Category slug already exists in organization")
        if code_check and row.code and row.code.strip().lower() == code_check:
            raise HTTPException(status_code=400, detail="Category code already exists in organization")


@router.get("")
async def list_categories(
    include_inactive: bool = False,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if current_user.role != UserRole.ADMIN:
        raise HTTPException(status_code=403, detail="Admin access required.")

    query = select(Category).where(Category.org_id == current_user.org_id)
    if not include_inactive:
        query = query.where(Category.is_active.is_(True))

    result = await db.execute(query.order_by(Category.name.asc()))
    categories = result.scalars().all()

    return [
        {
            "id": c.id,
            "name": c.name,
            "code": c.code,
            "slug": c.slug,
            "is_active": c.is_active,
        }
        for c in categories
    ]


@router.get("/{category_id}")
async def get_category(
    category_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if current_user.role != UserRole.ADMIN:
        raise HTTPException(status_code=403, detail="Admin access required.")

    result = await db.execute(
        select(Category).where(
            Category.id == category_id,
            Category.org_id == current_user.org_id,
        )
    )
    category = result.scalar_one_or_none()
    if not category:
        raise HTTPException(status_code=404, detail="Category not found.")

    return {
        "id": category.id,
        "name": category.name,
        "code": category.code,
        "slug": category.slug,
        "is_active": category.is_active,
    }


@router.post("")
async def create_category(
    payload: CategoryCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if current_user.role != UserRole.ADMIN:
        raise HTTPException(status_code=403, detail="Admin access required.")

    name = _normalize_text(payload.name)
    if len(name) < 2:
        raise HTTPException(status_code=400, detail="Category name must have at least 2 characters")

    slug = _slugify(name)
    if not slug:
        raise HTTPException(status_code=400, detail="Category slug could not be generated")

    code = _normalize_text(payload.code) if payload.code else None
    await _ensure_category_unique(db, current_user.org_id, name=name, slug=slug, code=code)

    category = Category(
        org_id=current_user.org_id,
        name=name,
        slug=slug,
        code=code,
        is_active=True,
    )
    db.add(category)
    await db.commit()
    await db.refresh(category)

    return {
        "id": category.id,
        "name": category.name,
        "code": category.code,
        "slug": category.slug,
        "is_active": category.is_active,
    }


@router.patch("/{category_id}")
async def update_category(
    category_id: int,
    payload: CategoryUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if current_user.role != UserRole.ADMIN:
        raise HTTPException(status_code=403, detail="Admin access required.")

    result = await db.execute(
        select(Category).where(
            Category.id == category_id,
            Category.org_id == current_user.org_id,
        )
    )
    category = result.scalar_one_or_none()
    if not category:
        raise HTTPException(status_code=404, detail="Category not found.")

    new_name = _normalize_text(payload.name) if payload.name is not None else category.name
    new_code = _normalize_text(payload.code) if payload.code is not None else category.code
    new_slug = _slugify(new_name) if payload.name is not None else category.slug

    if len(new_name) < 2:
        raise HTTPException(status_code=400, detail="Category name must have at least 2 characters")

    await _ensure_category_unique(
        db,
        current_user.org_id,
        name=new_name,
        slug=new_slug,
        code=new_code,
        exclude_id=category.id,
    )

    category.name = new_name
    category.slug = new_slug
    category.code = new_code
    if payload.is_active is not None:
        category.is_active = payload.is_active

    await db.commit()
    await db.refresh(category)

    return {
        "id": category.id,
        "name": category.name,
        "code": category.code,
        "slug": category.slug,
        "is_active": category.is_active,
    }


@router.delete("/{category_id}")
async def delete_category(
    category_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if current_user.role != UserRole.ADMIN:
        raise HTTPException(status_code=403, detail="Admin access required.")

    result = await db.execute(
        select(Category).where(
            Category.id == category_id,
            Category.org_id == current_user.org_id,
        )
    )
    category = result.scalar_one_or_none()
    if not category:
        raise HTTPException(status_code=404, detail="Category not found.")

    category.is_active = False
    await db.commit()

    return {"success": True}


@router.post("/seed-defaults")
async def seed_default_categories(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if current_user.role != UserRole.ADMIN:
        raise HTTPException(status_code=403, detail="Admin access required.")

    created = []
    skipped = []

    result = await db.execute(
        select(Category.slug).where(Category.org_id == current_user.org_id)
    )
    existing = {row[0] for row in result.all()}

    for item in DEFAULT_CATEGORIES:
        if item["slug"] in existing:
            skipped.append(item["slug"])
            continue
        category = Category(
            org_id=current_user.org_id,
            name=item["name"],
            slug=item["slug"],
            code=None,
            is_active=True,
        )
        db.add(category)
        created.append(item["slug"])

    await db.commit()

    return {
        "created": created,
        "skipped": skipped,
        "message": "Seeded defaults",
    }
