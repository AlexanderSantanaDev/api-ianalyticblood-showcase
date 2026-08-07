from slowapi import Limiter
from slowapi.util import get_remote_address

# ──────────────────────────────────────────
# 1) Limiter global  ─  60 req / min / IP
# ──────────────────────────────────────────
limiter = Limiter(
    key_func=get_remote_address, # Asegura que el rate limiting sea por IP
    default_limits=["60/minute"],# 60 peticiones por minuto
)

# Decorador abreviado, para que se importe así:
#   from app.core.rate_limit import limit
limit = limiter.limit
