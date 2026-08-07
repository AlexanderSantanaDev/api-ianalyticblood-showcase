from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from typing import List, Dict, Optional
from app.core.security import get_current_user, oauth2_scheme
from app.services.chat_service import chat_with_deepseek
import logging
from jose import jwt, JWTError
from app.core.config import settings

logger = logging.getLogger("app.api.chat")

router = APIRouter()

class ChatMessage(BaseModel):
    role: str # user | assistant
    content: str

    # Validar que el rol solo sea user o assistant (no system)
    @classmethod
    def __get_validators__(cls):
        yield cls.validate

    # Limitar longitud del contenido del mensaje
    from pydantic import field_validator
    @field_validator("role")
    @classmethod
    def validate_role(cls, v):
        if v not in ("user", "assistant"):
            raise ValueError("Rol inválido. Solo se permite 'user' o 'assistant'")
        return v

    @field_validator("content")
    @classmethod
    def validate_content(cls, v):
        if len(v) > 2000:
            raise ValueError("Mensaje demasiado largo (máx 2000 caracteres)")
        if not v.strip():
            raise ValueError("El mensaje no puede estar vacío")
        return v

class ChatRequest(BaseModel):
    messages: List[ChatMessage]

# Helper para obtener el usuario opcional sin lanzar 401 si falta el token
async def get_current_user_optional(request: Request) -> Optional[dict]:
    # Intentamos obtener el header Authorization manualmente
    auth_header = request.headers.get("Authorization")
    if not auth_header or not auth_header.startswith("Bearer "):
        return None
    
    token = auth_header.split(" ")[1]
    try:
        # Reutilizamos la lógica de decodificación de security.py de forma simplificada o importandola
        from app.core.security import get_current_user
        # Intentamos obtener el usuario real
        user = await get_current_user(token)
        return user
    except Exception:
        return None

@router.post("/chat")
async def chat_endpoint(
    request: ChatRequest,
    # Dependencia opcional mejorada. 
    # Permite acceso a invitados pero identifica a usuarios pro/free si están logueados.
    user: Optional[dict] = Depends(get_current_user_optional)  
):
    """
    Endpoint para chatear con la IA. Soporta usuarios logueados e invitados.
    """
    user_id = user.get('id', 'guest') if user else 'guest'
    user_plan = user.get('plan', 'visitor') if user else 'visitor'
    
    logger.info(f"Petición de chat recibida (ID: {user_id}, Plan: {user_plan})")
    
    if not request.messages:
        raise HTTPException(status_code=400, detail="La lista de mensajes no puede estar vacía")

    # Extraer mensajes del payload
    messages_payload = [{"role": m.role, "content": m.content} for m in request.messages]
    
    try:
        # await directo — chat_with_deepseek ahora es async nativo
        reply = await chat_with_deepseek(messages_payload, user_plan)
        
        return {
            "status": "success",
            "reply": reply,
            "quota_status": "active"
        }
        
    except Exception as e:
        logger.error(f"Error en endpoint /chat: {str(e)}")
        raise HTTPException(status_code=500, detail="Error procesando la respuesta de la IA")
