# Configuración y variables de entorno
import os
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    SECRET_KEY: str
    MONGO_URI: str
    # UPLOAD_DIR tiene default /tmp/uploads para Render (no hay disco persistente en Free)
    UPLOAD_DIR: str = "/tmp/uploads"
    DEEPSEEK_API_KEY: str
    DEEPSEEK_BASE_URL: str = "https://api.deepseek.com"
    HF_TOKEN: str

    # Stripe Config
    STRIPE_SECRET_KEY: str
    STRIPE_WEBHOOK_SECRET: str | None = None
    STRIPE_PRICE_ID_PREMIUM: str | None = None

    # URL del frontend (para redirecciones de Stripe)
    FRONTEND_URL: str = "http://localhost:3000"

    class Config:
        # env_file es opcional — en Render las vars se inyectan por env del sistema
        # En local, si existe .env lo lee. En Render (sin .env) las lee igualmente del entorno.
        env_file = ".env"
        env_file_encoding = "utf-8"
        # extra="ignore" evita crash si Render inyecta vars de plataforma que no esperamos
        extra = "ignore"


settings = Settings()

# crear UPLOAD_DIR al arrancar si no existe (en Render /tmp es efímero pero funciona)
os.makedirs(settings.UPLOAD_DIR, exist_ok=True)
