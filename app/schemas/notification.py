import enum

from pydantic import BaseModel, Field


class DevicePlatform(str, enum.Enum):
    ANDROID = "android"
    IOS = "ios"


class DeviceRegisterRequest(BaseModel):
    token: str = Field(..., min_length=20, max_length=1024)
    platform: DevicePlatform
    app_version: str | None = Field(default=None, max_length=50)


class DeviceUnregisterRequest(BaseModel):
    token: str = Field(..., min_length=20, max_length=1024)


class DeviceTokenResponse(BaseModel):
    success: bool
    message: str
