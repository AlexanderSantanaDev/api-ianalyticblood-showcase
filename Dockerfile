# ----- Base image -----
FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    # Fuerza solo 1 proceso de GC compacto — menos overhead de memoria en Python 3.12
    MALLOC_TRIM_THRESHOLD_=100000

RUN apt-get update && apt-get install -y \
    ca-certificates \
    tesseract-ocr \
    tesseract-ocr-spa tesseract-ocr-eng \
    poppler-utils \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# ----- Copiamos el código -----
COPY . .

# 1 solo worker en Render Free (512MB RAM)
# Con 4 workers cada fork cargaba ~150MB × 4 = 600MB → OOM
# Con 1 worker + --loop uvloop ahorramos ~250MB de RAM
# Si el plan sube a Pro (2GB+), cambiar a --workers 2
CMD ["uvicorn", "app.main:app", \
    "--host", "0.0.0.0", \
    "--port", "8000", \
    "--workers", "1", \
    "--loop", "uvloop"]
