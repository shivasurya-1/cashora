import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import get_current_user
from app.db.session import get_db
from app.models.notification import UserDeviceToken
from app.schemas.notification import DeviceRegisterRequest, DeviceTokenResponse, DeviceUnregisterRequest

router = APIRouter(prefix="/notifications", tags=["notifications"])


@router.post("/devices/register", response_model=DeviceTokenResponse)
async def register_device_token(
    payload: DeviceRegisterRequest,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    token = payload.token.strip()
    if not token:
        raise HTTPException(status_code=400, detail="Device token cannot be empty.")

    query = select(UserDeviceToken).where(UserDeviceToken.token == token)
    result = await db.execute(query)
    existing = result.scalar_one_or_none()

    now = datetime.datetime.now(datetime.timezone.utc)
    if existing:
        existing.user_id = current_user.id
        existing.platform = payload.platform.value
        existing.app_version = payload.app_version
        existing.is_active = True
        existing.last_seen_at = now
        message = "Device token updated successfully."
    else:
        db.add(
            UserDeviceToken(
                user_id=current_user.id,
                token=token,
                platform=payload.platform.value,
                app_version=payload.app_version,
                is_active=True,
                last_seen_at=now,
            )
        )
        message = "Device token registered successfully."

    try:
        await db.commit()
    except Exception as exc:
        await db.rollback()
        raise HTTPException(status_code=500, detail=f"Failed to register device token: {str(exc)}")

    return DeviceTokenResponse(success=True, message=message)


@router.post("/devices/unregister", response_model=DeviceTokenResponse)
async def unregister_device_token(
    payload: DeviceUnregisterRequest,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    token = payload.token.strip()
    if not token:
        raise HTTPException(status_code=400, detail="Device token cannot be empty.")

    query = select(UserDeviceToken).where(
        UserDeviceToken.token == token,
        UserDeviceToken.user_id == current_user.id,
    )
    result = await db.execute(query)
    existing = result.scalar_one_or_none()

    if not existing:
        return DeviceTokenResponse(success=True, message="Device token already unregistered.")

    existing.is_active = False
    existing.last_seen_at = datetime.datetime.now(datetime.timezone.utc)

    try:
        await db.commit()
    except Exception as exc:
        await db.rollback()
        raise HTTPException(status_code=500, detail=f"Failed to unregister device token: {str(exc)}")

    return DeviceTokenResponse(success=True, message="Device token unregistered successfully.")
