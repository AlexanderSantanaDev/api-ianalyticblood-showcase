# Modelos de usuario
import re
from datetime import datetime
from pydantic import BaseModel, EmailStr, field_validator

# Constantes de validación centralizadas
MIN_PASSWORD_LENGTH = 8
MAX_NAME_LENGTH = 100
MAX_PHONE_LENGTH = 20


class MedicalData(BaseModel):
    bloodType: str | None = None
    height: str | None = None
    weight: str | None = None
    allergies: str | None = None
    conditions: str | None = None

    # Validar longitud de campos médicos para prevenir payloads gigantes
    @field_validator("bloodType", "height", "weight", mode="before")
    @classmethod
    def validate_short_fields(cls, v):
        if v is not None and len(str(v)) > 50:
            raise ValueError("Campo demasiado largo (máx 50 caracteres)")
        return v

    @field_validator("allergies", "conditions", mode="before")
    @classmethod
    def validate_long_fields(cls, v):
        if v is not None and len(str(v)) > 500:
            raise ValueError("Campo demasiado largo (máx 500 caracteres)")
        return v


class UserBase(BaseModel):
    email: EmailStr
    name: str
    lastName: str | None = None
    phone: str | None = None
    medical_data: MedicalData | None = None
    plan: str | None = "free"
    subscription_status: str | None = "active"
    stripe_customer_id: str | None = None
    stripe_subscription_id: str | None = None

    # Validar longitud de nombre para prevenir payloads gigantes
    @field_validator("name", "lastName", mode="before")
    @classmethod
    def validate_name_length(cls, v):
        if v is not None and len(str(v)) > MAX_NAME_LENGTH:
            raise ValueError(f"Nombre demasiado largo (máx {MAX_NAME_LENGTH} caracteres)")
        return v

    # Validar formato de teléfono
    @field_validator("phone", mode="before")
    @classmethod
    def validate_phone(cls, v):
        if v is not None:
            cleaned = re.sub(r"[\s\-\(\)\+]", "", str(v))
            if len(cleaned) > MAX_PHONE_LENGTH or not cleaned.isdigit():
                raise ValueError("Teléfono inválido")
        return v


class UserCreate(UserBase):
    password: str
    terms_accepted: bool
    terms_version: str | None = "1.0"
    terms_accepted_at: datetime | None = None   # se completará en el service

    # Validación de fortaleza de contraseña
    # Antes: aceptaba "1" como contraseña — cualquier atacante podría bruteforcear
    @field_validator("password")
    @classmethod
    def validate_password_strength(cls, v):
        if len(v) < MIN_PASSWORD_LENGTH:
            raise ValueError(f"La contraseña debe tener al menos {MIN_PASSWORD_LENGTH} caracteres")
        if not re.search(r"[A-Z]", v):
            raise ValueError("La contraseña debe contener al menos una letra mayúscula")
        if not re.search(r"[a-z]", v):
            raise ValueError("La contraseña debe contener al menos una letra minúscula")
        if not re.search(r"\d", v):
            raise ValueError("La contraseña debe contener al menos un número")
        if len(v) > 128:
            raise ValueError("La contraseña no puede exceder 128 caracteres")
        return v

    # terms_accepted debe ser True obligatoriamente
    @field_validator("terms_accepted")
    @classmethod
    def validate_terms(cls, v):
        if not v:
            raise ValueError("Debes aceptar los términos y condiciones")
        return v


class User(UserBase):
    id: str
    terms_accepted: bool
    terms_version: str | None
    terms_accepted_at: datetime | None


class ProfileUpdate(BaseModel):
    name: str | None = None
    lastName: str | None = None
    phone: str | None = None
    medical_data: MedicalData | None = None
    # Antes: un usuario podía enviarse a sí mismo plan="premium" en el body del PUT /me
    # Esto era una escalada de privilegios CRÍTICA
    # Ahora solo el webhook de Stripe puede cambiar el plan (en subscription.py)

    @field_validator("name", "lastName", mode="before")
    @classmethod
    def validate_name_length(cls, v):
        if v is not None and len(str(v)) > MAX_NAME_LENGTH:
            raise ValueError(f"Nombre demasiado largo (máx {MAX_NAME_LENGTH} caracteres)")
        return v

    @field_validator("phone", mode="before")
    @classmethod
    def validate_phone(cls, v):
        if v is not None:
            cleaned = re.sub(r"[\s\-\(\)\+]", "", str(v))
            if len(cleaned) > MAX_PHONE_LENGTH or not cleaned.isdigit():
                raise ValueError("Teléfono inválido")
        return v
