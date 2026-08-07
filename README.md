# 🩸 IAnalyticBlood API

_Inteligencia para tus análisis de sangre._

> [!IMPORTANT]
> **SHOWCASE REPOSITORY**
> This is a public showcase repository for portfolio purposes. Sensitive AI prompts, clinical extraction algorithms, and environment configurations have been redacted for security and intellectual property protection.

![FastAPI](https://img.shields.io/badge/FastAPI-0.115.0-009688?logo=fastapi&logoColor=white)
![Docker](https://img.shields.io/badge/Docker-ready-2496ED?logo=docker&logoColor=white)
![MongoDB](https://img.shields.io/badge/MongoDB-Atlas-green?logo=mongodb&logoColor=white)
![Licence](https://img.shields.io/badge/License-MIT-blue)

> **TL;DR**  
> Sube un PDF o imagen de un informe de sangre y recibe:
>
> - parámetros estructurados
> - alerta visual
> - análisis médico + recomendaciones  
>   Todo en JSON limpio listo para usar.

---

## 🌟 Características

| Módulo                    | Descripción                                                           |
| ------------------------- | --------------------------------------------------------------------- |
| **OCR mejorado**          | Escala ×2, denoise a color y Tesseract `spa+eng`.                     |
| **PDF híbrido**           | Lee texto nativo con pdfplumber y cae a OCR si es escaneado.          |
| **Clasificador**          | Filtra archivos que _no_ parezcan un informe de sangre.               |
| **IA (DeepSeek)**         | Devuelve overview, parámetros, análisis y recomendaciones 100 % JSON. |
| **JWT Auth**              | Registro, login, protección `Bearer` en todos los endpoints privados. |
| **MongoDB**               | Persiste cada informe + metadatos + fecha.                            |
| **Endpoints UI-friendly** | `/summary`, `/stats/{param}`, `/dashboard` listos para NextJs/Vue.    |
| **Docker-ready**          | `docker compose up --build`.                                          |

---

## 📁 Estructura

IAnalyticBlood-API/
│
├── app/
│ ├── api/ # Routers FastAPI
│ ├── services/ # OCR, PDF, ML, DB…
│ ├── models/ # Pydantic schemas
│ └── core/ # Config + Security
├── uploads/ # Archivos temporales
├── Dockerfile
└── docker-compose.yml

## 🎯 Endpoints

| Método | Ruta                        | Descripción                                      |
| ------ | --------------------------- | ------------------------------------------------ |
| POST   | /auth/register              | Alta de usuario.                                 |
| POST   | /auth/login                 | Devuelve access_token.                           |
| POST   | /upload                     | Sube PDF/imagen → crea análisis.                 |
| GET    | /analysis/summary           | Mini-cards (id, date, summary, alert).           |
| GET    | /analysis/stats/{parameter} | Serie temporal para gráficas.                    |
| GET    | /analysis                   | Historial paginado.                              |
| GET    | /analysis/{id}              | Detalle completo.                                |
| GET    | /dashboard                  | KPIs (total, mes, estado, próximo recordatorio). |

## 📜 Licencia

© 2026 Alexander Javier Santana. Todos los derechos reservados.
