# Router para panel de administración

import time
import logging
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from app.core.security import get_current_admin
from app.services.db_service import (
    admin_get_users,
    admin_get_metrics,
    admin_update_user_plan,
    admin_update_user_status,
)

logger = logging.getLogger("app.admin")
router = APIRouter()


# Modelos de request 

class PlanUpdateRequest(BaseModel):
    """ Payload validado con Pydantic — solo planes permitidos."""
    plan: str

    def validate_plan(self) -> str:
        allowed = {"free", "premium", "enterprise"}
        if self.plan not in allowed:
            raise HTTPException(status_code=422, detail="Plan no válido")
        return self.plan


class StatusUpdateRequest(BaseModel):
    """ Payload validado con Pydantic — solo estados permitidos."""
    status: str

    def validate_status(self) -> str:
        allowed = {"active", "inactive", "suspended"}
        if self.status not in allowed:
            raise HTTPException(status_code=422, detail="Estado no válido")
        return self.status


# Endpoints 
@router.get("/metrics")
async def get_metrics(
    admin: dict = Depends(get_current_admin)
):
    """ Devuelve métricas globales de la plataforma.
        Solo accesible para administradores.
        Las queries MongoDB se ejecutan en paralelo para mínima latencia.
    """
    try:
        metrics = await admin_get_metrics()
        logger.info(f"[ADMIN] Métricas solicitadas por {admin['email']}")
        return metrics
    except Exception as e:
        # Log del error real en servidor, mensaje genérico al cliente
        logger.error(f"[ADMIN] Error obteniendo métricas: {e}")
        raise HTTPException(status_code=500, detail="Error al obtener métricas")


@router.get("/users")
async def get_users(
    page: int = Query(default=1, ge=1, le=10000),
    page_size: int = Query(default=20, ge=1, le=100),
    search: str = Query(default="", max_length=100),
    admin: dict = Depends(get_current_admin),
):
    """ Lista paginada de usuarios con búsqueda opcional.
        Excluye automáticamente campos sensibles (password, refresh_token, stripe_ids).
        La búsqueda se sanitiza antes de construir la query regex.
    """
    try:
        result = await admin_get_users(page=page, page_size=page_size, search=search)
        logger.info(
            f"[ADMIN] Listado de usuarios solicitado por {admin['email']} "
            f"(página {page}, búsqueda: '{search}')"
        )
        return result
    except Exception as e:
        logger.error(f"[ADMIN] Error listando usuarios: {e}")
        raise HTTPException(status_code=500, detail="Error al obtener usuarios")


@router.patch("/users/{user_id}/plan")
async def update_user_plan(
    user_id: str,
    body: PlanUpdateRequest,
    admin: dict = Depends(get_current_admin),
):
    """ Actualiza el plan de un usuario.
        El admin no puede cambiar su propio plan para evitar conflictos.
        Los valores de plan se validan estrictamente (free | premium | enterprise).
    """
    # Prevenir auto-modificación del admin
    if user_id == admin.get("id"):
        raise HTTPException(status_code=400, detail="No puedes modificar tu propio plan")

    # Validar ObjectId — evitar inyección MongoDB
    if not _is_valid_object_id(user_id):
        raise HTTPException(status_code=422, detail="ID de usuario inválido")

    plan = body.validate_plan()

    success = await admin_update_user_plan(user_id, plan)
    if not success:
        raise HTTPException(status_code=404, detail="Usuario no encontrado o sin cambios")

    logger.info(f"[ADMIN] {admin['email']} actualizó plan de {user_id} → {plan}")
    return {"success": True, "message": f"Plan actualizado a {plan}"}


@router.patch("/users/{user_id}/status")
async def update_user_status(
    user_id: str,
    body: StatusUpdateRequest,
    admin: dict = Depends(get_current_admin),
):
    """ Actualiza el estado de un usuario (activo / inactivo / suspendido).
        El admin no puede suspenderse a sí mismo.
    """
    # Prevenir auto-suspensión del admin
    if user_id == admin.get("id"):
        raise HTTPException(status_code=400, detail="No puedes modificar tu propio estado")

    # Validar ObjectId
    if not _is_valid_object_id(user_id):
        raise HTTPException(status_code=422, detail="ID de usuario inválido")

    status = body.validate_status()

    success = await admin_update_user_status(user_id, status)
    if not success:
        raise HTTPException(status_code=404, detail="Usuario no encontrado o sin cambios")

    logger.info(f"[ADMIN] {admin['email']} actualizó estado de {user_id} → {status}")
    return {"success": True, "message": f"Estado actualizado a {status}"}


@router.get("/health")
async def get_system_health(
    admin: dict = Depends(get_current_admin),
):
    """ Devuelve el estado de salud del sistema (API, DB, IA).
        Mide latencia real de MongoDB con un ping.
    """
    from app.services.db_service import db

    db_connected = False
    api_latency_ms = 0

    try:
        start = time.monotonic()
        await db.command("ping")
        api_latency_ms = round((time.monotonic() - start) * 1000, 2)
        db_connected = True
    except Exception as e:
        logger.error(f"[ADMIN] Fallo ping MongoDB: {e}")

    # Determinar estado global
    if not db_connected:
        status = "down"
    elif api_latency_ms > 500:
        status = "degraded"
    else:
        status = "healthy"

    # ai_service_available: se podría hacer un ping real a DeepSeek en el futuro
    return {
        "status": status,
        "api_latency_ms": api_latency_ms,
        "db_connected": db_connected,
        "ai_service_available": True,  # Provisional — sin ping real por ahora
        "uptime_seconds": _get_uptime(),
    }


# ── Helpers internos ──────────────────────────────────────────────────────────

def _is_valid_object_id(value: str) -> bool:
    """ Valida que un string sea un ObjectId válido de MongoDB — previene inyección."""
    from bson import ObjectId
    from bson.errors import InvalidId
    try:
        ObjectId(value)
        return True
    except (InvalidId, TypeError):
        return False


# Tiempo de inicio del proceso para calcular uptime
_START_TIME = time.monotonic()

def _get_uptime() -> float:
    """Devuelve los segundos que lleva corriendo el proceso."""
    return round(time.monotonic() - _START_TIME, 0)
