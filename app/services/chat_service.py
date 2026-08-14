import re
import httpx
from openai import AsyncOpenAI
from app.core.config import settings
import logging

logger = logging.getLogger("app.chat_service")

# Prompt del sistema especializado para IAnalytic Blood 
# El prompt del sistema ha sido ofuscado para el repositorio público.
# Aquí irían las instrucciones detalladas del comportamiento del LLM (reglas de oro, anti-jailbreak, formato, personalidad).
SYSTEM_PROMPT = """
[SYSTEM_PROMPT_OMITIDO_POR_SEGURIDAD]
"""

# Constantes de seguridad para sanitización de mensajes
MAX_MESSAGE_LENGTH = 2000  # Máximo de caracteres por mensaje
MAX_MESSAGES_HISTORY = 20  # Máximo de mensajes en el historial

# Cliente AsyncOpenAI singleton
_http_client = httpx.AsyncClient(
    timeout=httpx.Timeout(60.0, connect=10.0),
    limits=httpx.Limits(max_connections=10, max_keepalive_connections=5),
)

_ai_client = AsyncOpenAI(
    api_key=settings.DEEPSEEK_API_KEY,
    base_url=settings.DEEPSEEK_BASE_URL,
    http_client=_http_client,
)


# Sanitización de mensajes del usuario para prevenir prompt injection
def _sanitize_message(text: str) -> str:
    """Limpia un mensaje del usuario antes de enviarlo a DeepSeek."""
    # Truncar a longitud máxima
    text = text[:MAX_MESSAGE_LENGTH]
    # Eliminar tags HTML/XML que podrían confundir al modelo
    text = re.sub(r"<[^>]+>", "", text)
    # Eliminar secuencias que intentan cambiar el comportamiento del modelo
    text = re.sub(r"(?i)(ignore\s+previous|forget\s+your|you\s+are\s+now|act\s+as|system\s*:)", "[filtrado]", text)
    return text.strip()


# Función convertida a async — antes bloqueaba el threadpool
async def chat_with_deepseek(messages: list, plan: str = "visitor") -> str:
    """
    Recibe una lista de mensajes y el plan del usuario para ajustar el razonamiento.
    """
    logger.info(f"Iniciando chat con DeepSeek (Plan: {plan})")
    
    # Validar y limitar el número de mensajes del historial
    if len(messages) > MAX_MESSAGES_HISTORY:
        messages = messages[-MAX_MESSAGES_HISTORY:]
    
    # Sanitizar cada mensaje del usuario
    sanitized_messages = []
    for msg in messages:
        role = msg.get("role", "user")
        content = msg.get("content", "")
        if role == "user":
            content = _sanitize_message(content)
        # Solo permitir roles válidos
        if role in ("user", "assistant"):
            sanitized_messages.append({"role": role, "content": content})
    
    # Lógica de Razonamiento según Plan
    max_tokens = 3000 if plan == "premium" else 1000
    temperature = 0.5 if plan == "premium" else 0.7
    
    # Inyectamos el contexto del plan en el prompt del sistema
    plan_context = f"\n\nCONTEXTO DEL USUARIO: El usuario tiene un plan '{plan}'. "
    if plan == "premium":
        plan_context += "Proporciona análisis profundos, detallados y con razonamiento clínico avanzado."
    elif plan == "free":
        plan_context += "Proporciona respuestas útiles pero directas y concisas."
    else:
        plan_context += "Estás hablando con un visitante. Sé amable e invítalo a registrarse para ver todo el potencial."

    # Incluir el System Prompt al principio
    full_messages = [{"role": "system", "content": SYSTEM_PROMPT + plan_context}] + sanitized_messages
    
    try:
        # await nativo — ya no bloquea hilos del threadpool
        response = await _ai_client.chat.completions.create(
            model="deepseek-chat",
            messages=full_messages,
            max_tokens=max_tokens,
            temperature=temperature,
            stream=False
        )
        
        reply = response.choices[0].message.content
        logger.info("Respuesta del chat generada correctamente")
        return reply
        
    except Exception as e:
        logger.error(f"Error en chat_service: {str(e)}")
        # No exponer detalles del error al usuario
        return "Lo siento, mi conexión con el servidor clínico se ha visto interrumpida. Por favor, reintenta tu consulta en unos segundos."
