from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.roles import is_app_owner
from app.core.security import get_current_user
from app.db.session import get_db
from app.models.notification import UserDeviceToken
from app.models.organization import Organization
from app.models.user import User

router = APIRouter(prefix="/platform", tags=["platform-admin"])


class ToggleActivePayload(BaseModel):
    is_active: bool


def _require_app_owner(current_user: User) -> None:
    if not is_app_owner(current_user):
        raise HTTPException(status_code=403, detail="App owner access required")


@router.get("/stats")
async def get_platform_stats(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _require_app_owner(current_user)

    total_orgs = int((await db.execute(select(func.count(Organization.id)))).scalar() or 0)
    active_orgs = int((await db.execute(select(func.count(Organization.id)).where(Organization.is_active.is_(True)))).scalar() or 0)

    total_users = int((await db.execute(select(func.count(User.id)))).scalar() or 0)
    active_users = int((await db.execute(select(func.count(User.id)).where(User.is_active.is_(True)))).scalar() or 0)

    total_devices = int((await db.execute(select(func.count(UserDeviceToken.id)))).scalar() or 0)
    active_devices = int((await db.execute(select(func.count(UserDeviceToken.id)).where(UserDeviceToken.is_active.is_(True)))).scalar() or 0)

    return {
        "total_organizations": total_orgs,
        "active_organizations": active_orgs,
        "disabled_organizations": max(total_orgs - active_orgs, 0),
        "total_users": total_users,
        "active_users": active_users,
        "disabled_users": max(total_users - active_users, 0),
        "total_devices": total_devices,
        "active_devices": active_devices,
    }


@router.get("/organizations")
async def list_platform_organizations(
    include_disabled: bool = True,
    search: str | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _require_app_owner(current_user)

    user_count_sq = (
        select(User.org_id, func.count(User.id).label("user_count"))
        .group_by(User.org_id)
        .subquery()
    )

    admin_email_sq = (
        select(User.org_id, User.email.label("admin_email"), User.first_name, User.last_name)
        .where(User.role.in_(["admin", "super_admin"]))
        .order_by(User.org_id, User.created_at.asc(), User.id.asc())
        .distinct(User.org_id)
        .subquery()
    )

    query = (
        select(
            Organization.id,
            Organization.name,
            Organization.org_code,
            Organization.is_active,
            Organization.created_at,
            func.coalesce(user_count_sq.c.user_count, 0).label("user_count"),
            admin_email_sq.c.admin_email,
            admin_email_sq.c.first_name,
            admin_email_sq.c.last_name,
        )
        .outerjoin(user_count_sq, user_count_sq.c.org_id == Organization.id)
        .outerjoin(admin_email_sq, admin_email_sq.c.org_id == Organization.id)
        .order_by(Organization.created_at.desc())
    )

    filters = []
    if not include_disabled:
        filters.append(Organization.is_active.is_(True))

    if search:
        s = f"%{search.strip()}%"
        filters.append(or_(Organization.name.ilike(s), Organization.org_code.ilike(s), admin_email_sq.c.admin_email.ilike(s)))

    if filters:
        query = query.where(and_(*filters))

    rows = (await db.execute(query)).all()

    return [
        {
            "id": row.id,
            "name": row.name,
            "org_code": row.org_code,
            "is_active": row.is_active,
            "user_count": int(row.user_count or 0),
            "admin_name": " ".join([p for p in [row.first_name, row.last_name] if p]).strip() or None,
            "admin_email": row.admin_email,
            "created_at": row.created_at,
        }
        for row in rows
    ]


@router.patch("/organizations/{organization_id}")
async def toggle_organization_status(
    organization_id: int,
    payload: ToggleActivePayload,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _require_app_owner(current_user)

    org = (await db.execute(select(Organization).where(Organization.id == organization_id))).scalar_one_or_none()
    if not org:
        raise HTTPException(status_code=404, detail="Organization not found")

    org.is_active = payload.is_active
    await db.commit()
    await db.refresh(org)

    return {
        "id": org.id,
        "name": org.name,
        "org_code": org.org_code,
        "is_active": org.is_active,
        "created_at": org.created_at,
    }


@router.get("/users")
async def list_platform_users(
    include_disabled: bool = True,
    search: str | None = None,
    organization_id: int | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _require_app_owner(current_user)

    query = (
        select(
            User.id,
            User.first_name,
            User.last_name,
            User.email,
            User.role,
            User.is_active,
            User.org_id,
            Organization.name.label("organization_name"),
            Organization.is_active.label("organization_active"),
        )
        .join(Organization, Organization.id == User.org_id)
        .order_by(User.created_at.desc())
    )

    filters = []
    if not include_disabled:
        filters.append(User.is_active.is_(True))
        filters.append(Organization.is_active.is_(True))

    if organization_id is not None:
        filters.append(User.org_id == organization_id)

    if search:
        s = f"%{search.strip()}%"
        full_name = (User.first_name + " " + User.last_name)
        filters.append(
            or_(
                User.email.ilike(s),
                User.first_name.ilike(s),
                User.last_name.ilike(s),
                full_name.ilike(s),
                Organization.name.ilike(s),
                User.role.ilike(s),
            )
        )

    if filters:
        query = query.where(and_(*filters))

    rows = (await db.execute(query)).all()

    return [
        {
            "id": row.id,
            "full_name": " ".join([p for p in [row.first_name, row.last_name] if p]).strip(),
            "email": row.email,
            "role": (row.role or "").lower(),
            "organization_name": row.organization_name,
            "is_active": bool(row.is_active and row.organization_active),
        }
        for row in rows
    ]


@router.patch("/users/{user_id}")
async def toggle_user_status(
    user_id: int,
    payload: ToggleActivePayload,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _require_app_owner(current_user)

    user = (await db.execute(select(User).where(User.id == user_id))).scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    user.is_active = payload.is_active
    await db.commit()
    await db.refresh(user)

    org_name = (await db.execute(select(Organization.name).where(Organization.id == user.org_id))).scalar_one_or_none()

    return {
        "id": user.id,
        "full_name": f"{user.first_name} {user.last_name}".strip(),
        "email": user.email,
        "role": (user.role or "").lower(),
        "organization_name": org_name,
        "is_active": user.is_active,
    }
