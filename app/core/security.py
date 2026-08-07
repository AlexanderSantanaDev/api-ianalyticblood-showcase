# Lógica de autenticación y JWT
from datetime import datetime, timedelta
from passlib.context import CryptContext
from jose import JWTError, jwt
from fastapi import HTTPException, Depends
from fastapi.security import OAuth2PasswordBearer
from app.core.config import settings
import logging


# Encriptar/verificar contraseñas
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

def verify_password(plain_password, hashed_password):
    return pwd_context.verify(plain_password, hashed_password)

def get_password_hash(password):
    return pwd_context.hash(password)

# Crear JWT tokens
# Ahora incluye user_id y plan en el payload del token
def create_access_token(data: dict, expires_delta: timedelta | None = None):
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        # Vigencia por defecto 25 minutos
        expire = datetime.utcnow() + timedelta(minutes=25)
    to_encode.update({"exp": expire})
    # Codifica con la SECRET_KEY de .env
    encoded_jwt = jwt.encode(to_encode, settings.SECRET_KEY, algorithm="HS256")
    return encoded_jwt

# OAuth2PasswordBearer y get_current_user
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login")


# get_current_user ya NO hace query a MongoDB en cada request
# Antes: decodificaba JWT → sacaba email → query DB → devolvía user dict
# Ahora: decodifica JWT → devuelve los claims directamente (id, email, plan ya están en el token)
# Resultado: 0 queries de DB por request autenticado → mucho más rápido con muchos usuarios
async def get_current_user(token: str = Depends(oauth2_scheme)):
    """Obtiene al usuario actual a partir del token JWT sin roundtrip a DB."""
    try:
        # Decodificamos el token JWT
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=["HS256"])
        email: str = payload.get("sub")
        user_id: str = payload.get("user_id")
        
        if email is None or user_id is None:
            raise HTTPException(status_code=401, detail="Token inválido")

        # Devolvemos los datos directamente del JWT — sin query a MongoDB
        return {
            "id": user_id,
            "email": email,
            "plan": payload.get("plan", "free"),
            "name": payload.get("name"),
            # Role devuelto desde el JWT para uso en dependencies de admin
            "role": payload.get("role", "user"),
        }

    except JWTError as e:
        raise HTTPException(status_code=401, detail="Token inválido")


# Función auxiliar para cuando SÍ necesitamos datos frescos de DB
# Solo se usa en endpoints que requieren datos actualizados (ej: /me, /refresh)
async def get_current_user_from_db(token: str = Depends(oauth2_scheme)):
    """Obtiene al usuario actual CON query a MongoDB (para endpoints que necesitan datos frescos)."""
    from app.services.db_service import get_user_by_email
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=["HS256"])
        email: str = payload.get("sub")
        if email is None:
            raise HTTPException(status_code=401, detail="Token inválido")

        user = await get_user_by_email(email)
        if user is None:
            raise HTTPException(status_code=404, detail="Usuario no encontrado")
        
        return user

    except JWTError as e:
        raise HTTPException(status_code=401, detail="Token inválido")


# Dependency exclusiva de admin — lanza 403 si el rol del JWT no es "admin"
# Se usa en todos los endpoints de /api/admin/* para blindar el acceso sin exponer detalles
async def get_current_admin(current_user: dict = Depends(get_current_user)) -> dict:
    """Verifica que el usuario autenticado tenga rol de administrador.
    
    Lanza HTTP 403 si el usuario no tiene role='admin'.
    Nunca revela información sobre la existencia de la ruta (defensa contra enumeración).
    """
    if current_user.get("role") != "admin":
        # 403 genérico sin detalles de implementación
        raise HTTPException(status_code=403, detail="Acceso denegado")
    return current_user
