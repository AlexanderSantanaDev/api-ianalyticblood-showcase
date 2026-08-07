from datetime import datetime
from bson import ObjectId
from bson.errors import InvalidId
from motor.motor_asyncio import AsyncIOMotorClient
from app.core.config import settings
from app.models.analysis import AnalysisCreate
import logging

logger = logging.getLogger("app.db_service")

# Conexión con MongoDB utilizando el nombre de la base de datos de la URI
client = AsyncIOMotorClient(settings.MONGO_URI)
db = client.get_database()


# Crear índices al arrancar — sin índices, MongoDB hace full collection scan
# Con 10,000 análisis, cada query sin índice escanea los 10,000 documentos
async def ensure_indexes():
    """Crea índices necesarios para rendimiento en MongoDB."""
    # Índice en analyses.user_id — usado en TODAS las queries de análisis
    await db.analyses.create_index("user_id")
    # Índice compuesto para queries de dashboard (user_id + date)
    await db.analyses.create_index([("user_id", 1), ("date", -1)])
    # Índice único en users.email — usado en login, register, y auth
    await db.users.create_index("email", unique=True)
    # Índice en users.stripe_customer_id — usado en webhooks de Stripe
    await db.users.create_index("stripe_customer_id", sparse=True)
    logger.info("✅ Índices de MongoDB creados/verificados")

async def get_user_by_email(email: str) -> dict:
    """ Función para obtener un usuario por email. """
    user = await db.users.find_one({"email": email})
    if user:
        user["id"] = str(user.pop("_id"))  # Convertimos _id a id y lo casteamos a string
    return user
    
async def get_user_by_stripe_customer_id(customer_id: str) -> dict:
    """ Obtener usuario por stripe_customer_id. """
    user = await db.users.find_one({"stripe_customer_id": customer_id})
    if user:
        user["id"] = str(user.pop("_id"))
    return user


async def create_user(user: dict) -> str:
    """ Función para crear un usuario. """
    # Añadimos timestamp si viene el flag
    if user.get("terms_accepted") and not user.get("terms_accepted_at"):
        user["terms_accepted_at"] = datetime.utcnow()
    result = await db.users.insert_one(user)
    user_id = str(result.inserted_id)
    logger.info(f"Nuevo usuario creado con id: {user_id}")
    return user_id

async def update_user_refresh_token(user_id: str, refresh_token: str) -> None: 
    """ función para actualizar refresh token. """
    await db.users.update_one(
        {"_id": ObjectId(user_id)},
        {"$set": {"refresh_token": refresh_token}}
    )
    logger.info(f"Refresh token actualizado para el usuario: {user_id}")

async def update_user_profile(user_id: str, data: dict) -> bool:
    """ Función para actualizar el perfil del usuario. """
    result = await db.users.update_one(
        {"_id": ObjectId(user_id)},
        {"$set": data}
    )
    logger.info(f"Perfil actualizado para el usuario: {user_id}")
    return result.modified_count > 0

async def create_analysis(analysis: AnalysisCreate) -> str:
    """ Función para crear un análisis. """
    analysis_dict = analysis.dict()
    analysis_dict["date"] = datetime.utcnow()
    result = await db.analyses.insert_one(analysis_dict)
    analysis_id = str(result.inserted_id)
    logger.info(f"Nuevo análisis creado con id: {analysis_id}")
    return analysis_id

async def get_analysis(analysis_id: str) -> dict:
    """ Función para obtener un análisis por id. """
    # Validar ObjectId antes de usarlo — antes un ID malicioso causaba crash 500
    try:
        obj_id = ObjectId(analysis_id)
    except (InvalidId, TypeError):
        return None  # ID inválido → no encontrado (sin exponer error interno)
    analysis = await db.analyses.find_one({"_id": obj_id})
    if analysis:
        analysis["_id"] = str(analysis["_id"])
    return analysis

async def get_user_analyses(user_id: str, skip: int = 0, limit: int = 10) -> list:
    """ Función para obtener los análisis de un usuario. """
    # Limitar paginación para prevenir abuso (max 50 por página)
    limit = min(max(limit, 1), 50)
    skip = max(skip, 0)
    analyses = await db.analyses.find({"user_id": user_id}).sort("date", -1).skip(skip).limit(limit).to_list(length=limit)
    for doc in analyses:
        doc["_id"] = str(doc["_id"])
    return analyses

async def count_user_analyses(user_id: str) -> int:
    """ Cuenta el total de análisis realizados por un usuario históricamente. """
    return await db.analyses.count_documents({"user_id": user_id})

async def count_user_analyses_this_month(user_id: str) -> int:
    """ Cuenta el total de análisis realizados por un usuario en el mes actual. """
    month_start = datetime.utcnow().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    return await db.analyses.count_documents({
        "user_id": user_id,
        "date": {"$gte": month_start}
    })


# Funciones exclusivas del panel de ADMIN — solo accesibles con role="admin"
async def admin_get_users(
    page: int = 1,
    page_size: int = 20,
    search: str = "",
) -> dict:
    """ Devuelve usuarios paginados con búsqueda opcional por nombre o email.
       Solo debe llamarse desde endpoints protegidos con get_current_admin.
    """
    # Limitar paginación para prevenir abuso
    page_size = min(max(page_size, 1), 100)
    page = max(page, 1)
    skip = (page - 1) * page_size

    # Filtro de búsqueda — usamos regex insensible a mayúsculas (sin exposición de datos no solicitados)
    query: dict = {}
    if search and len(search.strip()) > 0:
        # Escapamos caracteres regex peligrosos antes de construir la query
        import re as _re
        safe_search = _re.escape(search.strip()[:100])  # máx 100 chars
        query = {
            "$or": [
                {"email": {"$regex": safe_search, "$options": "i"}},
                {"name":  {"$regex": safe_search, "$options": "i"}},
            ]
        }

    total = await db.users.count_documents(query)

    cursor = db.users.find(
        query,
        # Proyección: excluimos campos sensibles de la respuesta admin
        {"password": 0, "refresh_token": 0, "stripe_customer_id": 0, "stripe_subscription_id": 0}
    ).sort("_id", -1).skip(skip).limit(page_size)

    users = []
    async for u in cursor:
        u["id"] = str(u.pop("_id"))
        # Formatear fechas a ISO string
        if isinstance(u.get("terms_accepted_at"), datetime):
            u["terms_accepted_at"] = u["terms_accepted_at"].isoformat()
        # Añadir analysis_count real
        u["analysis_count"] = await db.analyses.count_documents({"user_id": u["id"]})
        # Proveedor inferido — si tiene password != "google", es credentials
        if not u.get("provider"):
            u["provider"] = "credentials"
        # Estado por defecto
        if not u.get("status"):
            u["status"] = "active"
        # Role por defecto
        if not u.get("role"):
            u["role"] = "user"
        # Último login (opcional)
        u["created_at"] = u.get("terms_accepted_at") or datetime.utcnow().isoformat()
        users.append(u)

    return {"users": users, "total": total, "page": page, "page_size": page_size}


async def admin_update_user_plan(user_id: str, plan: str) -> bool:
    """ Actualiza el plan de un usuario — solo desde el panel de admin."""
    valid_plans = {"free", "premium", "enterprise"}
    if plan not in valid_plans:
        return False
    result = await db.users.update_one(
        {"_id": ObjectId(user_id)},
        {"$set": {"plan": plan, "updated_at": datetime.utcnow()}}
    )
    logger.info(f"[ADMIN] Plan de usuario {user_id} actualizado a '{plan}'")
    return result.modified_count > 0


async def admin_update_user_status(user_id: str, status: str) -> bool:
    """ Actualiza el estado de un usuario — solo desde el panel de admin."""
    valid_statuses = {"active", "inactive", "suspended"}
    if status not in valid_statuses:
        return False
    result = await db.users.update_one(
        {"_id": ObjectId(user_id)},
        {"$set": {"status": status, "updated_at": datetime.utcnow()}}
    )
    logger.info(f"[ADMIN] Estado de usuario {user_id} actualizado a '{status}'")
    return result.modified_count > 0


async def admin_get_metrics() -> dict:
    """ Agrega métricas globales de la plataforma para el panel de admin.
    Ejecuta las agregaciones en paralelo para minimizar latencia.
    fechas calculadas con timedelta — sin riesgo de day-out-of-range.
    """
    from asyncio import gather
    from datetime import timedelta

    now = datetime.utcnow()

    # Usar timedelta en lugar de .replace(day=...) que explota con día < 30
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    # Inicio de la semana actual (lunes)
    week_start = today_start - timedelta(days=today_start.weekday())
    # Ventana de 90 días para capturar análisis históricos (antes 30 días)
    thirty_days_ago = today_start - timedelta(days=89)

    # Ejecución en paralelo de todas las queries de conteo 
    (
        total_users,
        total_analyses,
        analyses_today,
        analyses_week,
        active_today_result,
        active_week_result,
        plans_result,
        providers_result,
        top_users_result,
        analyses_per_day_result,
        new_users_per_day_result,
    ) = await gather(
        db.users.count_documents({}),
        db.analyses.count_documents({}),
        db.analyses.count_documents({"date": {"$gte": today_start}}),
        db.analyses.count_documents({"date": {"$gte": week_start}}),
        # Usuarios únicos que han hecho al menos un análisis hoy
        db.analyses.distinct("user_id", {"date": {"$gte": today_start}}),
        db.analyses.distinct("user_id", {"date": {"$gte": week_start}}),
        # Distribución de planes
        db.users.aggregate([
            {"$group": {"_id": "$plan", "count": {"$sum": 1}}}
        ]).to_list(length=10),
        # Distribución de proveedores
        db.users.aggregate([
            {"$group": {"_id": "$provider", "count": {"$sum": 1}}}
        ]).to_list(length=10),
        # Top 5 usuarios por número de análisis
        db.analyses.aggregate([
            {"$group": {"_id": "$user_id", "count": {"$sum": 1}}},
            {"$sort": {"count": -1}},
            {"$limit": 5},
        ]).to_list(length=5),
        # Thirty_days_ago calculado con timedelta — sin crash por día negativo
        # Análisis por día — últimos 30 días
        db.analyses.aggregate([
            {"$match": {"date": {"$gte": thirty_days_ago}}},
            {"$group": {
                "_id": {"$dateToString": {"format": "%Y-%m-%d", "date": "$date"}},
                "count": {"$sum": 1}
            }},
            {"$sort": {"_id": 1}},
        ]).to_list(length=90),
        # Nuevos usuarios por día — últimos 90 días
        # También filtramos por created_at como fallback si terms_accepted_at es null
        db.users.aggregate([
            {"$match": {
                "$or": [
                    {"terms_accepted_at": {"$gte": thirty_days_ago}},
                    {"created_at": {"$gte": thirty_days_ago}},
                ]
            }},
            {"$addFields": {
                "reg_date": {
                    "$ifNull": ["$terms_accepted_at", "$created_at"]
                }
            }},
            {"$group": {
                "_id": {"$dateToString": {"format": "%Y-%m-%d", "date": "$reg_date"}},
                "count": {"$sum": 1}
            }},
            {"$sort": {"_id": 1}},  # sintaxis corregida — sin doble brace
        ]).to_list(length=90),  # 90 días para coherencia con la ventana histórica
    )

    # Construir dict de planes (defaults a 0 si no hay datos)
    plans_map = {"free": 0, "premium": 0, "enterprise": 0}
    for p in plans_result:
        key = p["_id"] or "free"
        if key in plans_map:
            plans_map[key] = p["count"]

    # Construir dict de providers — "credentials" engloba los manuales sin provider guardado
    providers_map = {"credentials": 0, "google": 0}
    for p in providers_result:
        raw_key = p["_id"] or "credentials"
        key = raw_key if raw_key in providers_map else "credentials"
        providers_map[key] += p["count"]

    # Enriquecer top_users con nombre y email desde DB
    top_users = []
    for tu in top_users_result:
        try:
            u = await db.users.find_one(
                {"_id": ObjectId(tu["_id"])},
                {"name": 1, "email": 1}
            )
            if u:
                top_users.append({
                    "id": tu["_id"],
                    "name": u.get("name", "—"),
                    "email": u.get("email", "—"),
                    "analysis_count": tu["count"],
                })
        except Exception:
            pass

    return {
        "total_users": total_users,
        "active_users_today": len(active_today_result),
        "active_users_week": len(active_week_result),
        "total_analyses": total_analyses,
        "analyses_today": analyses_today,
        "analyses_week": analyses_week,
        "revenue_month": 0.0,   # 💡 Conectar con Stripe cuando esté disponible
        "users_by_plan": plans_map,
        "users_by_provider": providers_map,
        "top_users": top_users,
        "analyses_per_day": [{"date": r["_id"], "count": r["count"]} for r in analyses_per_day_result],
        "new_users_per_day": [{"date": r["_id"], "count": r["count"]} for r in new_users_per_day_result],
    }