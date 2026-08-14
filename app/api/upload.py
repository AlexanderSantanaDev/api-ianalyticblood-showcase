from fastapi import APIRouter, UploadFile, File, Depends, HTTPException, Request
from fastapi.security import OAuth2PasswordBearer
from app.models import user
from app.services.ocr_service import extract_text_from_image
from app.services.pdf_service import extract_text_from_pdf
from app.services.ml_service import analyze_with_deepseek
from app.models.analysis import AnalysisCreate
from app.core.config import settings
from app.core.security import get_current_user
from app.services.db_service import create_analysis, count_user_analyses_this_month, get_user_by_email, check_ip_preview_usage, mark_ip_preview_used
from app.services.report_classifier import is_blood_report
from app.core.rate_limit import limit 
from starlette.concurrency import run_in_threadpool 
import aiofiles   
import os
import uuid
import logging

logger = logging.getLogger("app.upload")

router = APIRouter()
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login")

MAX_FILE_MB  = 3
MAX_FILE_B   = MAX_FILE_MB * 1024 * 1024
ALLOWED_TYPES = {"application/pdf", "image/jpeg", "image/jpg", "image/png", "image/webp"}

def _tmp_path(name: str) -> str:
    ext = name.split(".")[-1]
    return os.path.join(settings.UPLOAD_DIR, f"{uuid.uuid4()}.{ext}")

async def _save_tmp(file: UploadFile) -> str:
    path = _tmp_path(file.filename)
    os.makedirs(settings.UPLOAD_DIR, exist_ok=True)
    async with aiofiles.open(path, "wb") as f:          # I/O no-bloqueante
        while chunk := await file.read(1024 * 1024):    # lee en 1 MB
            await f.write(chunk)
    await file.close()
    return path

@router.post("/upload/preview")
@limit("3/minute")  # Previene fuerza bruta sobre el endpoint gratuito
async def upload_preview_file(request: Request, file: UploadFile = File(...)):
    """ Endpoint para subir archivos de prueba gratuita (sin registro). """
    # Obtener IP real considerando proxys (Vercel)
    forwarded = request.headers.get("x-forwarded-for")
    ip = forwarded.split(",")[0].strip() if forwarded else request.client.host
    
    logger.info(f"Inicio del endpoint preview upload para la IP: {ip}")

    # Límite estricto de 1 prueba por IP
    has_used = await check_ip_preview_usage(ip)
    if has_used:
        raise HTTPException(
            status_code=429, 
            detail="Prueba gratuita agotada. Por favor, regístrate para seguir analizando tus informes."
        )

    # Validación estricta del tipo de archivo
    if file.content_type not in ALLOWED_TYPES:
        raise HTTPException(415, "Tipo de archivo no permitido")

    # Validación del tamaño antes de procesar
    clen = request.headers.get("content-length")
    if clen and int(clen) > MAX_FILE_B:
        raise HTTPException(413, f"Máx {MAX_FILE_MB} MB")

    tmp_path = await _save_tmp(file)
    if os.path.getsize(tmp_path) > MAX_FILE_B:
        os.remove(tmp_path)
        raise HTTPException(413, f"Máx {MAX_FILE_MB} MB")

    try:
        # OCR / Procesamiento no bloqueante
        if file.content_type == "application/pdf":
            text = await run_in_threadpool(extract_text_from_pdf, tmp_path)
        else:                                
            text = await run_in_threadpool(extract_text_from_image, tmp_path)

        if not await run_in_threadpool(is_blood_report, text):
            raise HTTPException(400, "El archivo no parece un informe de sangre válido")

        # Análisis con la IA en modo "free" (básico)
        analysis_raw = await analyze_with_deepseek(text, plan="free")
        if not isinstance(analysis_raw, dict):
            raise HTTPException(502, "DeepSeek devolvió algo inesperado")

        # INICIO SCRUBBING (Anti-DevTools)
        # Nunca enviamos el JSON completo al cliente. 
        # Calculamos puntuación y conteos, y falseamos el resto.
        params = analysis_raw.get("parameters", {})
        counts = {"optimal": 0, "attention": 0, "critical": 0}
        
        for k, v in params.items():
            st = v.get("status")
            if st == "normal":
                counts["optimal"] += 1
            elif st in ["bajo", "alto"]:
                counts["attention"] += 1
            elif st == "muy_alto":
                counts["critical"] += 1
                
        # Score inventado ponderado
        score = max(0, 100 - (counts["critical"] * 15) - (counts["attention"] * 5))
        
        # Extraer top 3 reales
        def param_weight(item):
            st = item[1].get("status")
            if st == "muy_alto": return 3
            if st in ["bajo", "alto"]: return 2
            return 1
            
        sorted_params = sorted(params.items(), key=param_weight, reverse=True)
        top_params = dict(sorted_params[:3])
        
        # Diccionario estático de descripciones comunes para que el frontend las renderice
        # Esto soluciona que el plan gratuito no envíe descripciones detalladas.
        COMMON_DESCRIPTIONS = {
            "glucosa": "La glucosa es la principal fuente de energía de las células. Niveles alterados pueden ser indicio de prediabetes, diabetes o resistencia a la insulina.",
            "colesterol": "Lípido esencial para las membranas celulares. Un exceso, especialmente de LDL, aumenta el riesgo de problemas cardiovasculares.",
            "triglicéridos": "Son el principal tipo de grasa transportada en el organismo. Niveles altos suelen relacionarse con dietas altas en azúcares o alcohol.",
            "creatinina": "Producto de desecho muscular filtrado por los riñones. Su medición es el mejor indicador rápido de la función renal global.",
            "urea": "Refleja la cantidad de nitrógeno en la sangre proveniente del metabolismo de las proteínas. Evalúa la función renal y el estado de hidratación.",
            "got": "Enzima presente principalmente en el corazón y el hígado. Sus niveles altos en sangre pueden indicar daño hepático o muscular.",
            "gpt": "Enzima que se encuentra mayoritariamente en el hígado. Es un marcador muy sensible para detectar daño o inflamación celular hepática.",
            "ácido úrico": "Producto final del metabolismo de las purinas. Si sus niveles se elevan, puede causar ataques de gota o cálculos renales.",
            "hierro": "Mineral vital para formar la hemoglobina. Su déficit causa anemia, mientras que su exceso puede dañar órganos como el hígado.",
            "vitamina d": "Hormona clave para el metabolismo óseo y la inmunidad. Su deficiencia es muy común y afecta la absorción de calcio.",
            "leucocitos": "Glóbulos blancos, responsables de la defensa del cuerpo. Un recuento alto indica infección o inflamación, mientras que uno bajo señala inmunosupresión.",
            "hemoglobina": "Proteína de los glóbulos rojos que transporta el oxígeno. Es el marcador definitivo para diagnosticar si existe anemia."
        }
        
        # Datos Lorem Ipsum falsos para desenfoque
        safe_parameters = {}
        for k, v in top_params.items():
            # Inyectar una descripción específica si existe, o una genérica si no
            key_lower = k.lower()
            desc = COMMON_DESCRIPTIONS.get(key_lower, f"La medición de {key_lower} es un marcador clave en los análisis de sangre para evaluar la función metabólica y general del cuerpo.")
            safe_parameters[k] = {**v, "description": desc, "is_real": True}
            
        dummy_params = {
            "Triglicéridos": {"value": 150, "unit": "mg/dL", "status": "normal", "reference_range": [0, 150], "description": "Los triglicéridos son un tipo de grasa (lípidos) que se encuentran en la sangre. El cuerpo almacena las calorías no utilizadas en forma de triglicéridos."},
            "Leucocitos": {"value": 8.5, "unit": "10^3/uL", "status": "normal", "reference_range": [4.0, 10.0], "description": "Los leucocitos o glóbulos blancos son una parte fundamental del sistema inmunológico que ayuda a combatir infecciones y otras enfermedades."},
            "Vitamina D": {"value": 20.5, "unit": "ng/mL", "status": "bajo", "reference_range": [30.0, 100.0], "description": "La vitamina D es esencial para mantener los huesos fuertes, ya que ayuda al cuerpo a absorber el calcio de la dieta."}
        }
        for k, v in dummy_params.items():
            safe_parameters[k] = {**v, "is_real": False}
            
        # Construimos las secciones con datos REALES de la IA.
        # DeepSeek devuelve "analysis_sections" con items reales en el plan "free".
        # Solo marcamos como is_real los 2 primeros items de cada sección;
        # el resto se difumina en el frontend para incentivar el registro.
        SECTION_META = {
            "seguimiento": {
                "title": "Seguimiento y Recomendaciones",
                "subtitle": "Su plan de acción de salud personalizado",
                "icon": "Activity",
                "visible_count": 2,
                "hidden_count": 3,
            },
            "introduccion": {
                "title": "Introducción y Resumen",
                "subtitle": "Visión general de sus resultados",
                "icon": "FileText",
                "visible_count": 2,
                "hidden_count": 3,
            },
            "evaluacion_general": {
                "title": "Evaluación General de Salud",
                "subtitle": "Estado actual de sus principales sistemas",
                "icon": "Heart",
                "visible_count": 2,
                "hidden_count": 4,
            },
            "analisis_detallado": {
                "title": "Análisis Detallado de Salud",
                "subtitle": "Desglose por sistemas y órganos",
                "icon": "Microscope",
                "visible_count": 2,
                "hidden_count": 3,
            },
            "factores_riesgo": {
                "title": "Análisis de Factores de Riesgo",
                "subtitle": "Identificación temprana de vulnerabilidades",
                "icon": "AlertTriangle",
                "visible_count": 2,
                "hidden_count": 3,
            },
            "conclusion": {
                "title": "Conclusión y Próximos Pasos",
                "subtitle": "El camino hacia su bienestar óptimo",
                "icon": "Compass",
                "visible_count": 2,
                "hidden_count": 3,
            },
        }

        # Obtenemos las secciones reales que devolvió DeepSeek para el plan "free"
        raw_sections = analysis_raw.get("analysis_sections", [])

        # Construimos el array final combinando metadatos + items reales con flags
        analysis_sections = []
        for raw_section in raw_sections:
            section_key = raw_section.get("section", "")
            meta = SECTION_META.get(section_key)
            if not meta:
                # Si DeepSeek devuelve una sección inesperada, la ignoramos
                continue

            raw_items = raw_section.get("items", [])
            visible = meta["visible_count"]

            # Primeros N items visibles (is_real: True), el resto difuminado (is_real: False)
            structured_items = [
                {"text": item, "is_real": i < visible}
                for i, item in enumerate(raw_items)
                if item  # Filtramos items nulos o vacíos
            ]

            analysis_sections.append({
                "title": meta["title"],
                "subtitle": meta["subtitle"],
                "icon": meta["icon"],
                "items": structured_items,
                "hidden_count": max(0, len(structured_items) - visible),
            })
            
        recs = analysis_raw.get("recommendations", [])
        real_rec = recs[0] if recs else "Sigue las indicaciones de tu médico y mantén un estilo de vida saludable."
        safe_recs = [
            {"text": real_rec, "is_real": True},
            {"text": "Se sugiere una evaluación dietética para optimizar la ingesta de micronutrientes y estabilizar marcadores hepáticos alterados.", "is_real": False},
            {"text": "Considerar prueba de función tiroidea (TSH, T4 libre) en el próximo control debido a ligeras fluctuaciones observadas.", "is_real": False}
        ]

        scrubbed_analysis = {
            "overview": analysis_raw.get("overview", {}),
            "score": score,
            "counts": counts,
            "total_parameters_hidden": max(0, len(params) - 3),
            "parameters": safe_parameters,
            "analysis_sections": analysis_sections,
            "recommendations": safe_recs
        }

        # Registrar la IP como usada SOLO cuando todo el análisis fue exitoso
        await mark_ip_preview_used(ip)
        
        # Seguridad de datos: No se guarda nada en la base de datos de los pacientes. 
        # Devuelve la respuesta SCRUBBED para que la vea y se esfume si recarga.
        return {"status": "success", "analysis": scrubbed_analysis}

    finally:
        # Destrucción segura del archivo físico pase lo que pase
        if os.path.exists(tmp_path):
            os.remove(tmp_path)


@router.post("/upload")
@limit("5/minute")  # Limita a 5 peticiones por minuto
async def upload_file(request: Request ,file: UploadFile = File(...), user: dict = Depends(get_current_user)):
    """ Endpoint para subir archivos. """
    logger.info(f"Inicio del endpoint upload para el usuario: {user.get('id')}")

    # Lógica de límites (Premium Barrier)
    plan = user.get("plan", "free")
    if plan == "free":
        # Verificación en DB por si el usuario acaba de pagar y el JWT está desactualizado
        db_user = await get_user_by_email(user["email"])
        if db_user and db_user.get("plan") in ["premium", "enterprise"]:
            plan = db_user.get("plan")
        
        if plan == "free":
            monthly_analyses = await count_user_analyses_this_month(user["id"])
            # Incentiva la conversion a Premium para quienes necesiten mas analisis.
            if monthly_analyses >= 1:
                raise HTTPException(
                    status_code=402, 
                    detail="Limite mensual alcanzado (1/1). Pasate a Premium para subidas ilimitadas!"
                )

    # Tipo MIME
    if file.content_type not in ALLOWED_TYPES:
        raise HTTPException(415, "Tipo de archivo no permitido")

    # Tamaño – primero con Content-Length, por si existe
    clen = request.headers.get("content-length")
    if clen and int(clen) > MAX_FILE_B:
        raise HTTPException(413, f"Máx {MAX_FILE_MB} MB")

    # Guarda en tmp y vuelve a comprobar el tamaño real
    tmp_path = await _save_tmp(file)
    if os.path.getsize(tmp_path) > MAX_FILE_B:
        os.remove(tmp_path)
        raise HTTPException(413, f"Máx {MAX_FILE_MB} MB")

    # Procesamiento del archivo (OCR o PDF)
    try:
        # Usamos run_in_threadpool para no bloquear el Event Loop con OCR y PDF (CPU-bound)
        if file.content_type == "application/pdf":
            text = await run_in_threadpool(extract_text_from_pdf, tmp_path)
        else:                                # cualquier image/*
            text = await run_in_threadpool(extract_text_from_image, tmp_path)

        # Validación de informe de sangre en hilo separado (CPU-bound)
        if not await run_in_threadpool(is_blood_report, text):
            raise HTTPException(
                400,
                "El archivo no parece un informe de sangre válido"
            )

        # await directo → no bloquea ningún hilo, escala infinitamente
        analysis_raw = await analyze_with_deepseek(text, plan)
        if not isinstance(analysis_raw, dict):
            raise HTTPException(502, "DeepSeek devolvió algo inesperado")

        # Normalización defensiva de analysis_sections antes de pasar a Pydantic.
        # Modelo devuelve items como strings planos ["texto1", "texto2"]
        # y puede omitir title/subtitle/icon. Pydantic espera objetos AnalysisSectionItem
        # con {text: str, is_real: bool} y los 3 campos de metadata obligatorios.
        # Este normalizer convierte el output crudo de la IA al contrato tipado correcto.
        SECTION_META_REGISTERED = {
            "seguimiento":        {"title": "Seguimiento y Recomendaciones",  "subtitle": "Tu plan de acción de salud personalizado",      "icon": "Activity"},
            "introduccion":       {"title": "Introducción y Resumen",          "subtitle": "Visión general de tus resultados",               "icon": "FileText"},
            "evaluacion_general": {"title": "Evaluación General de Salud",    "subtitle": "Estado actual de tus principales sistemas",      "icon": "Heart"},
            "analisis_detallado": {"title": "Análisis Detallado de Salud",    "subtitle": "Desglose por sistemas y órganos",                "icon": "Microscope"},
            "factores_riesgo":    {"title": "Análisis de Factores de Riesgo", "subtitle": "Identificación temprana de vulnerabilidades",    "icon": "AlertTriangle"},
            "conclusion":         {"title": "Conclusión y Próximos Pasos",    "subtitle": "El camino hacia tu bienestar óptimo",            "icon": "Compass"},
        }

        raw_sections = analysis_raw.get("analysis_sections", [])
        normalized_sections = []
        for sec in raw_sections:
            section_key = sec.get("section", "")
            meta = SECTION_META_REGISTERED.get(section_key, {})

            # Convertir items: pueden venir como strings o como dicts {text, is_real}
            raw_items = sec.get("items", [])
            normalized_items = []
            for item in raw_items:
                if isinstance(item, str) and item.strip():
                    # ← DeepSeek devolvió string plano → lo convertimos al formato correcto
                    normalized_items.append({"text": item.strip(), "is_real": True})
                elif isinstance(item, dict) and item.get("text"):
                    # ← Ya viene en formato correcto, solo aseguramos is_real=True
                    normalized_items.append({"text": item["text"], "is_real": True})
                # items nulos o vacíos se descartan

            normalized_sections.append({
                # Usamos los campos del meta si la IA los omitió
                "title":       sec.get("title")    or meta.get("title",    section_key),
                "subtitle":    sec.get("subtitle") or meta.get("subtitle", ""),
                "icon":        sec.get("icon")     or meta.get("icon",     "CircleDot"),
                "items":       normalized_items,
                "hidden_count": 0,  # Para usuarios registrados no hay items ocultos en BD
            })

        # Sustituimos el campo crudo por el normalizado antes de construir AnalysisCreate
        analysis_raw["analysis_sections"] = normalized_sections

        analysis = AnalysisCreate(
            user_id=user["id"],
            file_type=file.content_type,
            **analysis_raw,
        )
        analysis_id = await create_analysis(analysis)
        return {"status": "success", "analysis_id": analysis_id}

    finally:
        # Limpieza pase lo que pase
        if os.path.exists(tmp_path):
            os.remove(tmp_path)