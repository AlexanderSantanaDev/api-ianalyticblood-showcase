import json
import re
import httpx
from openai import AsyncOpenAI
from app.core.config import settings
import logging


logger = logging.getLogger("app.ml_service")

# Cliente AsyncOpenAI creado UNA VEZ a nivel de módulo (singleton)
# Antes se creaba uno nuevo POR CADA análisis → nuevas conexiones TCP/TLS cada vez
_http_client = httpx.AsyncClient(
    timeout=httpx.Timeout(90.0, connect=10.0),  # Timeout de 90s para DeepSeek
    limits=httpx.Limits(max_connections=20, max_keepalive_connections=10),  # Pool de conexiones reutilizable
)

_ai_client = AsyncOpenAI(
    api_key=settings.DEEPSEEK_API_KEY,
    base_url=settings.DEEPSEEK_BASE_URL,
    http_client=_http_client,
)


# Función convertida a async — ya no bloquea el threadpool
async def analyze_with_deepseek(text: str, plan: str = "free") -> dict:
    """Analiza texto de informe de sangre con DeepSeek (async, no-bloqueante)."""
    logger.info(f"Enviando análisis a DeepSeek (async) - Plan: {plan}")

    # Adaptación del prompt según el plan
    if plan == "free": interpretation_instruction = """
    Realiza un análisis REAL y basado en los datos extraídos del informe.
    Genera las secciones del análisis con viñetas concretas y personalizadas.
    Devuelve una lista vacía `[]` para recommendations y analysis.
    """
    else: interpretation_instruction = "Realiza un análisis EXHAUSTIVO, detallado y profesional. Proporciona recomendaciones personalizadas y accionables para mejorar los biomarcadores fuera de rango."

    # La estructura del prompt JSON cambia según el plan para evitar enviar
    # datos de más al cliente no autenticado y mantener segmentación de datos.
    if plan == "free":
        # Prompt exclusivo para preview — datos reales en lenguaje claro y accesible.
        # El prompt de IA de extracción (Plan Básico) ha sido ofuscado para proteger la propiedad intelectual del proyecto.
        prompt = f"""
        [PROMPT_FREE_OMITIDO_POR_SEGURIDAD]
        """
    else:
        # Prompt para usuarios con cuenta (free/premium) 
        # El prompt de IA de extracción (Plan Premium) ha sido ofuscado para proteger la propiedad intelectual del proyecto.
        prompt = f"""
        [PROMPT_PREMIUM_OMITIDO_POR_SEGURIDAD]
        """

    logger.debug(f"Prompt enviado a DeepSeek: {prompt[:150]}...")
    try:
        # await nativo en vez de run_in_threadpool → no consume hilos del pool
        response = await _ai_client.chat.completions.create(
            model="deepseek-chat",
            messages=[
                {"role": "system", "content": "Eres un asistente médico experto."},
                {"role": "user", "content": prompt}
            ],
            max_tokens=4000,
            stream=False
        )
        raw = response.choices[0].message.content
        analysis_dict = _force_json(raw)
        # Fallback defensivo para campos que DeepSeek puede omitir.
        # En plan free el prompt pide `[]` pero DeepSeek a veces simplemente
        # no incluye la clave → el modelo Pydantic lanza ValidationError.
        # setdefault garantiza la clave sin sobrescribir si ya viene informada.
        analysis_dict.setdefault("recommendations", [])
        analysis_dict.setdefault("analysis", [])
        # Fallback defensivo para analysis_sections — si DeepSeek lo omite
        # en el plan "free", el builder de upload.py simplemente devuelve lista vacía.
        analysis_dict.setdefault("analysis_sections", [])
        logger.info("Respuesta recibida de DeepSeek correctamente")
        return analysis_dict
    except Exception as e:
        # Raise en vez de return string — el caller ya captura excepciones
        logger.error(f"Error al analizar con DeepSeek: {e}")
        raise RuntimeError(f"Error al analizar con DeepSeek: {str(e)}")
    

def _force_json(text: str) -> dict:
    """
    Intenta parsear texto a JSON.
    • Elimina fences ```json ... ```
    • Extrae la primera llave {...} si viene mezclado con bla-bla.
    """
    # 1. Quita fences ```json y ```
    cleaned = re.sub(r"```(?:json)?|```", "", text, flags=re.I).strip()

    # 2. Si sigue fallando, captura el primer bloque { ... }
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", cleaned, flags=re.S)
        if m:
            return json.loads(m.group(0))
        raise  # re-lanza si ni así es JSON