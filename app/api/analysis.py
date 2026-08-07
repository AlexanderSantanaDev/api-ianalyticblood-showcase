# Endpoints para consultar análisis
import asyncio
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException
from fastapi.security import OAuth2PasswordBearer
from app.services.db_service import get_analysis, get_user_analyses, db, get_user_by_email
from app.core.security import get_current_user 
from app.utils.helpers import calculate_next_reminder

router = APIRouter()
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login")

# Rutas fijas
""" Home / dashboard → tarjetas "Últimos análisis". """
@router.get("/analysis/summary")
async def get_analyses_summary(skip: int = 0, limit: int = 10,
                               current_user: dict = Depends(get_current_user)):
    analyses = await get_user_analyses(current_user["id"], skip, limit)
    return [
        {
            "id": a["_id"],
            "date": a["date"],
            "summary": a["overview"]["summary"],
            "alert_level": a["overview"]["alert_level"]
        } for a in analyses
    ]
    
""" Gráficas de evolución (Glucosa, Colesterol…). """
@router.get("/analysis/stats/{parameter_name}")
async def get_parameter_series(parameter_name: str,
                               current_user: dict = Depends(get_current_user)):
    # Bloqueo de característica Premium: Gráficas de evolución
    plan = current_user.get("plan", "free")
    if plan == "free":
        # Verificación en DB por si el usuario acaba de pagar y el JWT está desactualizado
        db_user = await get_user_by_email(current_user["email"])
        if db_user and db_user.get("plan") in ["premium", "enterprise"]:
            plan = db_user.get("plan")
            
        if plan == "free":
            raise HTTPException(status_code=403, detail="Las estadísticas evolutivas requieren un plan Premium.")

    cursor = db.analyses.find({"user_id": current_user["id"],
                               f"parameters.{parameter_name}": {"$exists": True}},
                              projection={"date": 1, f"parameters.{parameter_name}.value": 1}
                             ).sort("date", 1)
    series = [{"date": doc["date"], "value": doc["parameters"][parameter_name]["value"]}
              async for doc in cursor]
    return series

""" KPI del header ("Total análisis", "Este mes", estado general y aviso de próximo control). """
@router.get("/dashboard")
async def dashboard(current_user: dict = Depends(get_current_user)):
    # 3 queries en PARALELO con asyncio.gather
    # Antes: 3 queries secuenciales → ~90ms con 30ms latencia por query
    # Ahora: todas en paralelo → ~30ms total
    month_start = datetime.utcnow().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    
    total_task = db.analyses.count_documents({"user_id": current_user["id"]})
    monthly_task = db.analyses.count_documents({
        "user_id": current_user["id"],
        "date": {"$gte": month_start}
    })
    last_task = db.analyses.find_one(
        {"user_id": current_user["id"]},
        sort=[("date", -1)]
    )
    
    total, monthly, last_analysis = await asyncio.gather(
        total_task, monthly_task, last_task
    )
    
    return {
        "analyses_total": total,
        "analyses_this_month": monthly,
        "general_state": last_analysis["overview"]["general_state"] if last_analysis else "—",
        "next_reminder": calculate_next_reminder(last_analysis)
    }
    
# Rutas dinámicas
@router.get("/analysis")
async def get_analyses(skip: int = 0, limit: int = 10, 
    current_user: dict = Depends(get_current_user)):
    # Eliminado token duplicado — get_current_user ya valida el token
    user_id = current_user["id"]                
    analyses = await get_user_analyses(user_id, skip, limit)
    return {"status": "success", "data": analyses}

@router.get("/analysis/{analysis_id}")
async def get_analysis_details(analysis_id: str, current_user: dict = Depends(get_current_user)):
    # Añadido Depends(get_current_user) — antes cualquier usuario podía ver cualquier análisis
    analysis = await get_analysis(analysis_id)
    if not analysis:
        raise HTTPException(status_code=404, detail="Análisis no encontrado")
    
    # Verificar que el análisis pertenece al usuario autenticado
    if analysis.get("user_id") != current_user["id"]:
        raise HTTPException(status_code=403, detail="No tienes acceso a este análisis")
    
    return {"status": "success", "data": analysis}