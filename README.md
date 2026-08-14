# 🧠 IAnalytic Blood - Core API & AI Engine

> © 2026 Alexander Santana. Todos los derechos reservados.

![Python](https://img.shields.io/badge/Python-3776AB?style=for-the-badge&logo=python&logoColor=white) ![AI](https://img.shields.io/badge/AI_Engine-000000?style=for-the-badge&logo=openai&logoColor=white) ![Security](https://img.shields.io/badge/Security-Strict-success?style=for-the-badge)

Este repositorio contiene la **API Analítica Core** y el **Motor de Inteligencia Artificial** que da vida a IAnalytic Blood. Actúa como el cerebro del sistema, encargado de procesar informes de laboratorio, extraer biomarcadores mediante modelos avanzados de visión y lenguaje (OCR + NLP) y devolver conclusiones estructuradas al frontend.

> [!IMPORTANT]
> **SHOWCASE REPOSITORY**
> This is a public showcase repository for portfolio purposes. Sensitive AI prompts, clinical extraction algorithms, and environment configurations have been redacted for security and intellectual property protection.

---

## 🚀 Características Principales

- **Procesamiento Inteligente:** Recepción de informes en formato PDF e imagen. El motor se encarga de limpiar, normalizar y estructurar los datos extraídos.
- **Análisis Clínico por IA:** Utilización de modelos de Inteligencia Artificial de última generación para entender el contexto médico, extraer métricas (como Hematíes, Colesterol, Glucosa) e identificar su estado (Normal, Alto, Bajo, Crítico) basándose en los rangos de referencia.
- **Generación de Insights:** La IA no solo extrae números, sino que genera un resumen ejecutivo y recomendaciones de salud adaptadas a los resultados del paciente.
- **Procesamiento Stateless (Sin estado):** Por motivos de privacidad y seguridad, la API no almacena permanentemente los informes ni la información identificable del usuario. Procesa la solicitud y devuelve el resultado, eliminando los archivos temporales.

---

## 💻 Arquitectura y Stack Tecnológico

- **Lenguaje:** Python 3.x
- **Framework de API:** FastAPI / Flask (Diseñado para respuestas rápidas y manejo de concurrencia).
- **Motor de Extracción:** Pipelines de OCR de alta precisión para digitalizar imágenes médicas.
- **Motor de Inteligencia Artificial:** Integración con LLMs avanzados para la comprensión profunda de textos médicos y estructuración de datos en JSON estricto.
- **Validación de Datos:** Uso de esquemas (Pydantic / Dataclasses) para garantizar que la respuesta de la IA siempre cumpla con el formato esperado por el frontend.

---

## 🛡️ Ciberseguridad y Blindaje del Backend

El backend es la última línea de defensa y maneja la lógica más delicada. Se han implementado las siguientes medidas:

### 1. Autenticación Server-to-Server

La API no está expuesta directamente al público general. Solo acepta peticiones provenientes del Frontend autenticado de Next.js mediante el uso de **Tokens de Servicio Internos (Service Keys)**.

### 2. Rate Limiting y Protección DDoS

Para proteger el coste computacional del motor de IA, los _endpoints_ críticos están protegidos con estrictas cuotas de peticiones (Rate Limiting) que evitan ataques de denegación de servicio o abuso por parte de bots.

### 3. Sanitización de Archivos

- **Análisis de Payload:** Verificación profunda de firmas de archivos (Magic Bytes) para asegurar que un archivo `.pdf` es realmente un PDF y no un ejecutable camuflado.
- **Límites estrictos:** Control del peso máximo en MB y dimensiones de imagen para prevenir ataques de agotamiento de memoria (OOM).

### 4. Privacidad y Seguridad de la IA (Prompt Injection)

- **Anonimización:** Los prompts enviados al motor de IA están diseñados para no requerir ni incluir datos personales identificables (PII) del paciente.
- **Defensa contra Inyecciones:** Los datos leídos por OCR se "escapan" y estructuran antes de inyectarse en el modelo, evitando ataques de _Prompt Injection_ donde un documento manipulado podría alterar el comportamiento de la IA.

---

## ⚡ Flujo de Procesamiento (Pipeline)

1.  **Recepción:** El endpoint seguro recibe el archivo (PDF/IMG).
2.  **Validación y Preprocesamiento:** Se chequea la integridad y se extrae el texto puro / imágenes.
3.  **Análisis por IA:**
    - Fase 1: Extracción de parámetros (Biomarcadores, Valores, Unidades, Rangos).
    - Fase 2: Evaluación clínica (Cálculo del estado del parámetro respecto al rango).
    - Fase 3: Generación de insights (Resumen y recomendaciones).
4.  **Estructuración:** Conversión de la respuesta de la IA a un contrato JSON tipado estrictamente.
5.  **Respuesta y Limpieza:** Se devuelve el JSON al frontend y se purga la memoria del servidor.

---

> El motor analítico de IAnalytic Blood representa la fusión perfecta entre ingeniería de software robusta e Inteligencia Artificial de vanguardia aplicada a la salud.
