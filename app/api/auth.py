from datetime import timedelta, datetime
import logging
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.security import OAuth2PasswordRequestForm
from jose import JWTError, jwt
from pydantic import BaseModel, EmailStr
from app.models.user import UserCreate, ProfileUpdate
from app.core.security import create_access_token, get_password_hash, verify_password, oauth2_scheme, get_current_user_from_db
from app.services.db_service import get_user_by_email, create_user, update_user_refresh_token, update_user_profile
from app.core.rate_limit import limit
from app.core.config import settings

# Logger para registrar operaciones sensibles sin exponer trazas al cliente
logger = logging.getLogger("app.api.auth")

router = APIRouter()


# Modelo tipado para Google login — antes aceptaba body: dict (cualquier cosa)
class GoogleLoginRequest(BaseModel):
    email: EmailStr
    name: str | None = None
    picture: str | None = None
    provider: str  # Debe ser "google"


# Helper para generar tokens con datos completos del usuario
# Antes solo incluía {"sub": email}, ahora incluye user_id, plan, name
# Esto permite que get_current_user funcione SIN query a MongoDB
def _make_tokens(user: dict) -> dict:
    """Genera access + refresh tokens con datos del usuario embebidos."""
    token_data = {
        "sub": user["email"],
        "user_id": user["id"],            # ID embebido en JWT
        "plan": user.get("plan", "free"), # Plan embebido en JWT
        "name": user.get("name"),          # Nombre embebido en JWT
        # Role embebido en JWT — el frontend (NextAuth) lo leerá para mostrar/ocultar el admin panel
        "role": user.get("role", "user"),
    }
    
    access_token = create_access_token(
        data=token_data,
        expires_delta=timedelta(minutes=25)
    )
    
    refresh_token = create_access_token(
        data={**token_data, "type": "refresh"},
        expires_delta=timedelta(days=7)
    )
    
    return {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "token_type": "bearer",
        "plan": user.get("plan", "free"),
        # Devolvemos el role para que NextAuth lo persista en la sesión cliente
        "role": user.get("role", "user"),
    }


@router.get("/me")
async def read_users_me(current_user: dict = Depends(get_current_user_from_db)):
    """ endpoint para obtener los datos del usuario actual """    
    # Usa get_current_user_from_db para datos frescos (no el JWT rápido)
    # Eliminamos datos sensibles antes de enviar
    if "password" in current_user:
        del current_user["password"]
    if "refresh_token" in current_user:
        del current_user["refresh_token"]
    return current_user

@router.put("/me")
async def update_user_me(
    profile_data: ProfileUpdate, 
    current_user: dict = Depends(get_current_user_from_db)
):
    """ endpoint para actualizar el perfil del usuario. """
    # Usa get_current_user_from_db para datos frescos
    update_data = profile_data.dict(exclude_unset=True)
    
    # Manejo especial de medical_data para no sobrescribir todo si solo llega un campo
    if "medical_data" in update_data and current_user.get("medical_data"):
        combined_medical = current_user["medical_data"].copy()
        combined_medical.update(update_data["medical_data"])
        update_data["medical_data"] = combined_medical

    success = await update_user_profile(current_user["id"], update_data)
    
    if not success:
         # Podría ser que no hubo cambios reales
         return {"status": "no_changes", "message": "No se realizaron cambios"}
         
    return {"status": "success", "message": "Perfil actualizado correctamente"}


#  Modelo tipado y validado para el cambio de contraseña
class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str


@router.put("/change-password")
@limit("5/minute")  # 🔒 Rate limit estricto para evitar ataques de fuerza bruta
async def change_password(
    request: Request,
    body: ChangePasswordRequest,
    current_user: dict = Depends(get_current_user_from_db),
):
    """
     Endpoint seguro para cambiar la contraseña del usuario.
    - Verifica que la contraseña actual sea correcta antes de actualizar.
    - Solo accesible para usuarios con contraseña (no OAuth/Google).
    - Rate limiting: máximo 5 intentos por minuto.
    """
    # Bloquear cambio de contraseña para usuarios de Google (contraseña dummy)
    stored_password = current_user.get("password", "")
    if not stored_password or verify_password("google", stored_password):
        raise HTTPException(
            status_code=400,
            detail="Los usuarios registrados con Google no pueden cambiar la contraseña aquí."
        )

    # Verificar que la contraseña actual proporcionada sea correcta
    if not verify_password(body.current_password, stored_password):
        raise HTTPException(
            status_code=400,
            detail="La contraseña actual es incorrecta."
        )

    # Validación mínima de la nueva contraseña (el frontend ya valida, pero el backend también)
    if len(body.new_password) < 8:
        raise HTTPException(
            status_code=422,
            detail="La nueva contraseña debe tener al menos 8 caracteres."
        )

    # Actualizar contraseña en base de datos con hash seguro
    new_hashed = get_password_hash(body.new_password)
    from app.services.db_service import db
    from bson import ObjectId
    await db.users.update_one(
        {"_id": ObjectId(current_user["id"])},
        {"$set": {"password": new_hashed}}
    )

    return {"status": "success", "message": "Contraseña actualizada correctamente."}


@router.post("/register")
@limit("10/5minute")
async def register(request: Request, user: UserCreate):
    if await get_user_by_email(user.email):
        raise HTTPException(status_code=400, detail="Email ya registrado")
    
    hashed_password = get_password_hash(user.password)
    user_dict = user.dict()
    user_dict["password"] = hashed_password
    user_id = await create_user(user_dict)
    return {"status": "success", "user_id": user_id}

@router.post("/login")
@limit("10/5minute")
async def login(request: Request, form_data: OAuth2PasswordRequestForm = Depends()):
    user = await get_user_by_email(form_data.username)
    if not user or not verify_password(form_data.password, user["password"]):
        #  Mensaje genérico — no revelar si el email existe o no
        raise HTTPException(status_code=401, detail="Credenciales inválidas")
    
    # Usar helper _make_tokens que embebe user_id, plan, name en el JWT
    tokens = _make_tokens(user)
    await update_user_refresh_token(user["id"], tokens["refresh_token"])
    return {"status": "success", **tokens}

@router.post("/refresh")
@limit("20/minute")  # Rate limit en refresh para prevenir abuso de tokens
async def refresh_token(request: Request, refresh_token: str = Depends(oauth2_scheme)):
    """ Endpoint para refrescar el token de acceso. """
    try:
        payload = jwt.decode(refresh_token, settings.SECRET_KEY, algorithms=["HS256"])
        if payload.get("type") != "refresh":
            raise HTTPException(status_code=401, detail="Token inválido")
        email = payload.get("sub")
        if email is None:
            raise HTTPException(status_code=401, detail="Token inválido")
    except JWTError:
        raise HTTPException(status_code=401, detail="Token inválido")
    
    # En refresh SÍ consultamos DB para obtener datos frescos (plan actualizado, etc.)
    user = await get_user_by_email(email)
    if user is None or user.get("refresh_token") != refresh_token:
        raise HTTPException(status_code=401, detail="Token inválido")
    
    # Usar helper _make_tokens con datos frescos de DB
    tokens = _make_tokens(user)
    await update_user_refresh_token(user["id"], tokens["refresh_token"])
    return tokens
    

@router.post("/google")
@limit("10/5minute")
async def google_login(request: Request, body: GoogleLoginRequest):
    """ Endpoint para manejar Google OAuth. """
    # body tipado con Pydantic — antes aceptaba dict sin validación
    if body.provider != "google":
        raise HTTPException(status_code=400, detail="Proveedor inválido")

    user = await get_user_by_email(body.email)
    if not user:
        # Registrar nuevo usuario
        user_dict = {
            "email": body.email,
            "name": body.name,
            "password": get_password_hash("google"),  # Contraseña dummy
            "terms_accepted": True,
            "terms_version": "1.0",
            "terms_accepted_at": datetime.utcnow(),
            "plan": "free",
            "subscription_status": "active"
        }
        user_id = await create_user(user_dict)
        user = await get_user_by_email(body.email)
    
    # Usar helper _make_tokens
    tokens = _make_tokens(user)
    await update_user_refresh_token(user["id"], tokens["refresh_token"])
    return tokens



# Eliminar cuenta
@router.delete("/me")
@limit("3/hour")  
async def delete_account(
    request: Request,  # Requerido por slowapi para aplicar rate limiting por IP
    current_user: dict = Depends(get_current_user_from_db),
):
    """
      Elimina permanentemente la cuenta del usuario autenticado.
    - Borra todos sus análisis de MongoDB.
    - Borra su documento de usuario de MongoDB.
    - Operación irreversible.
    """
    from app.services.db_service import db
    from bson import ObjectId

    user_id = current_user["id"]

    # 1. Eliminar todos los análisis del usuario
    result_analyses = await db.analyses.delete_many({"user_id": user_id})
    logger.info(f"🗑️ Eliminados {result_analyses.deleted_count} análisis del usuario {user_id}")

    # 2. Eliminar el documento del usuario
    result_user = await db.users.delete_one({"_id": ObjectId(user_id)})
    if result_user.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Usuario no encontrado.")

    logger.info(f"🗑️ Cuenta eliminada permanentemente: {user_id} ({current_user.get('email', 'N/A')})")
    return {"status": "success", "message": "Cuenta eliminada permanentemente."}


# EXPORTAR DATOS DEL USUARIO
def _serialize_for_json(obj):
    """
      Helper recursivo que convierte tipos no serializables de MongoDB a tipos JSON válidos:
    - datetime → ISO 8601 string
    - ObjectId → string
    - dict / list → recursivo
    Necesario porque MongoDB devuelve datetime nativos que json.dumps no sabe manejar.
    """
    from bson import ObjectId as BsonObjectId

    if isinstance(obj, dict):
        return {k: _serialize_for_json(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [_serialize_for_json(item) for item in obj]
    elif isinstance(obj, datetime):
        # Convertir datetime a ISO 8601 string con sufijo Z (UTC)
        return obj.isoformat() + "Z" if obj.tzinfo is None else obj.isoformat()
    elif isinstance(obj, BsonObjectId):
        # Convertir ObjectId BSON a string
        return str(obj)
    return obj


@router.get("/me/export")
@limit("5/hour")
async def export_my_data(
    request: Request, 
    current_user: dict = Depends(get_current_user_from_db),
):
    """
     Devuelve un JSON con todos los datos del usuario:
    - Perfil (sin campos sensibles como password/refresh_token)
    - Todos sus análisis históricos
    Compatible con GDPR/LOPD — derecho de portabilidad de datos.
    """
    from fastapi.responses import JSONResponse
    from app.services.db_service import db

    user_id = current_user["id"]

    # Limpiar datos sensibles del perfil antes de exportar
    safe_profile = {k: v for k, v in current_user.items()
                    if k not in ("password", "refresh_token", "stripe_customer_id",
                                 "stripe_subscription_id", "_id")}
    safe_profile["id"] = user_id

    # Obtener todos los análisis del usuario (sin límite para exportación completa)
    analyses_cursor = db.analyses.find({"user_id": user_id}).sort("date", -1)
    analyses = []
    async for doc in analyses_cursor:
        doc["_id"] = str(doc["_id"])
        analyses.append(doc)

    export_payload = {
        "exported_at": datetime.utcnow().isoformat() + "Z",
        "profile": safe_profile,
        "analyses": analyses,
        "total_analyses": len(analyses),
    }

    # Serializar recursivamente para convertir datetime/ObjectId a tipos JSON válidos
    serialized_payload = _serialize_for_json(export_payload)

    logger.info(f"Exportación de datos solicitada por usuario: {user_id}")

    # Devolvemos como JSON con cabecera de descarga
    return JSONResponse(
        content=serialized_payload,
        headers={
            "Content-Disposition": f"attachment; filename=ianalyticblood_export_{user_id[:8]}.json"
        }
    )