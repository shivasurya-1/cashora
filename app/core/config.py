from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    # Existing Database & Security
    DATABASE_URL: str
    SECRET_KEY: str
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 1440

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

    class Config:
        env_file = ".env"
        extra = "allow"  # Allow extra env vars without crashing

settings = Settings()