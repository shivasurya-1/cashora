from fastapi import HTTPException

from app.models.user import UserRole


ADMIN_ROLES = {UserRole.ADMIN, UserRole.SUPER_ADMIN}


def normalize_role(value: str) -> str:
    return (value or "").strip().lower()


def is_app_owner(user) -> bool:
    return normalize_role(str(user.role)) == UserRole.APP_OWNER.value


def is_super_admin(user) -> bool:
    return normalize_role(str(user.role)) == UserRole.SUPER_ADMIN.value


def is_admin_like(user) -> bool:
    role = normalize_role(str(user.role))
    return role in {UserRole.ADMIN.value, UserRole.SUPER_ADMIN.value}


def is_branch_admin(user) -> bool:
    role = normalize_role(str(user.role))
    return role == UserRole.ADMIN.value and getattr(user, "branch_id", None) is not None


def enforce_branch_scope(user, requested_branch_id: int | None) -> int | None:
    if is_super_admin(user):
        return requested_branch_id

    if normalize_role(str(user.role)) != UserRole.ADMIN.value:
        raise HTTPException(status_code=403, detail="Admin access required.")

    if getattr(user, "branch_id", None) is not None:
        if requested_branch_id is not None and requested_branch_id != user.branch_id:
            raise HTTPException(status_code=403, detail="Branch-scoped admin cannot access other branches.")
        return user.branch_id

    return requested_branch_id


def can_assign_role(actor_role: str, target_role: str) -> bool:
    actor = normalize_role(actor_role)
    target = normalize_role(target_role)

    if actor in {UserRole.SUPER_ADMIN.value, UserRole.ADMIN.value}:
        return target in {
            UserRole.ADMIN.value,
            UserRole.ACCOUNTANT.value,
            UserRole.REQUESTOR.value,
        }

    return False
