import secrets
from typing import List, Optional
from pydantic import AnyHttpUrl, PostgresDsn, RedisDsn, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # App
    APP_NAME: str = "ShuvoPay"
    DEBUG: bool = False
    SECRET_KEY: str = secrets.token_urlsafe(32)
    ENVIRONMENT: str = "production"

    # Database
    DATABASE_URL: PostgresDsn
    DB_POOL_SIZE: int = 10
    DB_MAX_OVERFLOW: int = 20

    # Redis
    REDIS_URL: RedisDsn

    # JWT (RS256)
    JWT_PRIVATE_KEY: str = ""
		  JWT_PUBLIC_KEY: str = ""
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 15
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7

    # Encryption
    AES_ENCRYPTION_KEY: str       # 32-byte hex string for AES-256-GCM

    # CORS
    CORS_ORIGINS: List[str] = []

    @field_validator("CORS_ORIGINS", mode="before")
    @classmethod
    def parse_cors(cls, v):
        if isinstance(v, str):
            return [origin.strip() for origin in v.split(",")]
        return v

    # Admin bootstrap
    ADMIN_EMAIL: str
    ADMIN_PASSWORD: str

    # Match engine
    MATCH_ENGINE_TOLERANCE: float = 0.0         # BDT tolerance for amount match
    MATCH_TIME_WINDOW_MINUTES: int = 30
    MATCH_CONFIDENCE_THRESHOLD: float = 0.95

    # Webhooks
    WEBHOOK_MAX_RETRIES: int = 7
    WEBHOOK_TIMEOUT_SECONDS: int = 10

    # Rate limits
    RATE_LIMIT_SMS_REPORT: int = 200            # per device per minute
    RATE_LIMIT_LOGIN: int = 5                   # per IP per minute

    # FCM
    FCM_SERVER_KEY: Optional[str] = None

    # Audit log retention
    AUDIT_LOG_RETENTION_DAYS: int = 90

    # Allowed hosts
    ALLOWED_HOSTS: List[str] = ["*"]

    @field_validator("ALLOWED_HOSTS", mode="before")
    @classmethod
    def parse_hosts(cls, v):
        if isinstance(v, str):
            return [h.strip() for h in v.split(",")]
        return v


settings = Settings()
