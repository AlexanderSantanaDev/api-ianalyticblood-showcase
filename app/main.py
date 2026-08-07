# Punto de entrada principal (FastAPI app)
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from slowapi.middleware import SlowAPIMiddleware          
from slowapi.errors import RateLimitExceeded              
from fastapi.responses import JSONResponse   
from app.api import auth, upload, analysis, chat, subscription, admin  
from app.core.rate_limit import limiter  
from app.services.db_service import ensure_indexes

# Usar lifespan en vez de on_event (deprecated en FastAPI moderno)
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: crear índices de MongoDB
    await ensure_indexes()
    logger.info("✅ Startup completado — índices verificados")
    yield
    # Shutdown (si necesitas cleanup futuro, va aquí)
    logger.info("🛑 Shutdown de la API")

app = FastAPI(title="IAnalyticBlood API", lifespan=lifespan)

app.state.limiter = limiter
app.add_exception_handler(
    RateLimitExceeded,
    lambda request, exc: JSONResponse(
        status_code=429,
        content={"detail": "Demasiadas peticiones, espera un momento."},
    ),
)
app.add_middleware(SlowAPIMiddleware)

# CORS 
origins = [
    "http://localhost:3000",      # Next.js en dev
    "https://app-ianalyticblood.vercel.app",   # producción
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,       # cookies / Authorization
    allow_methods=["*"],
    allow_headers=["*"],
)

# Configuración básica del logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] [%(name)s] %(message)s"
)
logger = logging.getLogger(__name__)
logger.info("Iniciando la IAnalyticBlood API")


# Todos los routers ahora tienen el prefijo /api
app.include_router(auth.router, prefix="/api/auth", tags=["auth"])
app.include_router(upload.router, prefix="/api", tags=["upload"])
app.include_router(analysis.router, prefix="/api", tags=["analysis"])
app.include_router(chat.router, prefix="/api", tags=["chat"]) # chatbot con ia
app.include_router(subscription.router, prefix="/api/subscription", tags=["subscription"])
# Router de admin registrado con prefijo /api/admin — protegido internamente con get_current_admin
app.include_router(admin.router, prefix="/api/admin", tags=["admin"])