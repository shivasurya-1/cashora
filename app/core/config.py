from pydantic_settings import BaseSettings
from typing import List

class Settings(BaseSettings):
    # Existing Database & Security
    DATABASE_URL: str
    SECRET_KEY: str
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 1440

    # CORS — comma-separated list of allowed origins, e.g.
    # ALLOWED_ORIGINS=https://app.cashora.com,https://staging.cashora.com
    # Defaults to ["*"] so local dev works out of the box.
    ALLOWED_ORIGINS: str = "*"

    @property
    def cors_origins(self) -> List[str]:
        if self.ALLOWED_ORIGINS.strip() == "*":
            return ["*"]
        return [o.strip() for o in self.ALLOWED_ORIGINS.split(",") if o.strip()]

    # --- SMTP Configuration ---
    SMTP_USERNAME: str
    SMTP_PASSWORD: str
    SMTP_FROM: str
    SMTP_PORT: int
    SMTP_SERVER: str

    # --- Cloudinary Configuration ---
    CLOUDINARY_CLOUD_NAME: str
    CLOUDINARY_API_KEY: str
    CLOUDINARY_API_SECRET: str
    CLOUDINARY_FOLDER: str = "petty-cash-receipts"

    # --- Push Notification Configuration (FCM) ---
    FCM_ENABLED: bool = False
    FCM_SERVICE_ACCOUNT_FILE: str | None = None
    FCM_PROJECT_ID: str | None = None
    FCM_DRY_RUN: bool = False
    FIREBASE_PROJECT_ID: str | None = None
    FIREBASE_CLIENT_EMAIL: str | None = None
    FIREBASE_PRIVATE_KEY: str | None = None

    class Config:
        env_file = ".env"
        extra = "allow"  # Allow extra env vars without crashing

settings = Settings()