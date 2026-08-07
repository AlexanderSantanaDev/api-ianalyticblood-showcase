from fastapi import APIRouter, UploadFile, File, Depends, HTTPException, Request
from fastapi.security import OAuth2PasswordBearer
from app.models import user
from app.services.ocr_service import extract_text_from_image
from app.services.pdf_service import extract_text_from_pdf
from app.services.ml_service import analyze_with_deepseek
from app.models.analysis import AnalysisCreate
from app.core.config import settings
from app.core.security import get_current_user
from app.services.db_service import create_analysis, count_user_analyses_this_month, get_user_by_email
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

# Eliminada función save_uploaded_file (dead code síncrono que nunca se usaba)

@router.post("/upload")
@limit("5/minute")  # Limita a 5 peticiones por minuto
async def upload_file(request: Request ,file: UploadFile = File(...), user: dict = Depends(get_current_user)):
    """ Endpoint para subir archivos. """
    logger.info(f"Inicio del endpoint upload para el usuario: {user.get('id')}")

    # --- Lógica de límites (Premium Barrier) ---
    plan = user.get("plan", "free")
    if plan == "free":
        # Verificación en DB por si el usuario acaba de pagar y el JWT está desactualizado
        db_user = await get_user_by_email(user["email"])
        if db_user and db_user.get("plan") in ["premium", "enterprise"]:
            plan = db_user.get("plan")
        
        if plan == "free":
            monthly_analyses = await count_user_analyses_this_month(user["id"])
            if monthly_analyses >= 5:
                raise HTTPException(
                    status_code=402, 
                    detail="Límite mensual alcanzado (5/5). ¡Pásate a Premium para subidas ilimitadas! 🚀"
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

        # await nativo — analyze_with_deepseek ahora es async
        # Antes: run_in_threadpool(analyze_with_deepseek, text) → consumía hilo del pool
        # Ahora: await directo → no bloquea ningún hilo, escala infinitamente
        analysis_raw = await analyze_with_deepseek(text, plan)
        if not isinstance(analysis_raw, dict):
            raise HTTPException(502, "DeepSeek devolvió algo inesperado")

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