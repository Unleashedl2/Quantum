from decimal import Decimal
from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_env: str = "development"
    app_name: str = "Quantum Store"
    timezone: str = "America/Caracas"
    secret_key: str = "dev-only-change-me"
    frontend_origins: str = "http://localhost:5173"

    database_url: str = "postgresql+psycopg://quantumstore:quantumstore@localhost:5432/quantumstore"
    db_pool_size: int = 10
    db_max_overflow: int = 10

    reservation_hours: int = 24                 # reserva de stock sin pago declarado
    shipping_flat_usd: Decimal = Decimal("0.00")  # 0 = costo de envío a coordinar con el transportista
    session_ttl_hours: int = 12
    cookie_secure: bool = False
    login_max_attempts: int = 5
    login_lock_minutes: int = 15

    s3_endpoint: str = ""
    s3_bucket: str = ""
    s3_access_key: str = ""
    s3_secret_key: str = ""
    s3_region: str = "us-east-1"
    s3_public_base_url: str = ""   # p. ej. https://cdn.tudominio.com o https://bucket.s3.amazonaws.com
    max_upload_mb: int = 5

    public_base_url: str = "http://localhost:5173"
    token_ttl_minutes_reset: int = 60

    init_temp_password: str = ""
    master_email: str = "master@quantumstore.local"
    admin_email: str = "admin@quantumstore.local"

    @property
    def is_production(self) -> bool:
        return self.app_env == "production"

    @property
    def cors_origins(self) -> list[str]:
        return [o.strip() for o in self.frontend_origins.split(",") if o.strip()]

    def assert_production_safe(self) -> None:
        if self.is_production:
            if self.secret_key.startswith("dev-only") or len(self.secret_key) < 32:
                raise RuntimeError("SECRET_KEY inseguro en producción")
            if not self.cookie_secure:
                raise RuntimeError("COOKIE_SECURE debe ser true en producción")


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
