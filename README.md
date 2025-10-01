<div align="center">

# 🌦️ Benpo SIATA Dashboard

Plataforma unificada y moderna para observar en tiempo casi real el pulso meteorológico del Valle de Aburrá: pronósticos WRF por zona, red de estaciones, heatmaps dinámicos y un pipeline ETL resiliente que conversa de forma inteligente con las fuentes del SIATA.

![Arquitectura](https://img.shields.io/badge/Arquitectura-Modular-3D8BFD?style=flat) ![ETL](https://img.shields.io/badge/ETL-Robusto-2566A8) ![Stack](https://img.shields.io/badge/Stack-Flask_|_PostgreSQL_|_Leaflet-1F4C7D)

</div>

---

## ✨ Visión General

El sistema recoge periódicamente:

1. Pronósticos WRF zonales (multi‑día)
2. Inventario de estaciones (metadatos)
3. Mediciones instantáneas por estación (temperatura, humedad, lluvia, viento)

Los procesa (limpieza, normalización, idempotencia), los almacena en PostgreSQL y expone una API limpia que alimenta un frontend single‑page con mapa interactivo + panel de pronósticos.

---

## 🧬 Relación entre Fuentes de Datos

| Fuente                  | Endpoint SIATA            | Frecuencia                         | Destino en DB                                      | Uso en Frontend                            |
| ----------------------- | ------------------------- | ---------------------------------- | -------------------------------------------------- | ------------------------------------------ |
| Pronósticos WRF (zonas) | `wrf{zona}.json`          | Cada 10 min (ETL completo)         | Tabla `pronosticos` (upsert por zona+fecha)        | Tarjetas de pronóstico y detalle día a día |
| Listado estaciones      | `PluviometricaMeteo.json` | Cada 10 min (ETL completo)         | Tabla `estaciones` (upsert por código)             | Metadatos + posicionamiento en mapa        |
| Medición por estación   | `{codigo}.json`           | Cada 30 s (job rápido incremental) | Tabla `mediciones` (insert si no existe timestamp) | Tooltip dinámico + heatmaps                |

La clave: dividimos el pipeline en DOS ritmos — uno “lento” (estructura y pronóstico) y otro “rápido” (telemetría viva). Esto reduce latencia percibida y presión sobre la API pública.

---

## � Flujo ETL Inteligente

| Etapa               | Descripción                            | Estrategia Clave                                                                  |
| ------------------- | -------------------------------------- | --------------------------------------------------------------------------------- |
| Fetch zonal         | Descarga de todos los `wrf{zona}.json` | Reintentos exponenciales + log granular zona                                      |
| Fetch estaciones    | Catálogo completo de la red            | Upsert masivo para mantener activas y actualizar coordenadas                      |
| Fetch mediciones    | Una petición por estación activa       | Procesado incremental (30s) + desactivación de “muertas” (24h)                    |
| Limpieza            | Filtrado de placeholders (-999)        | Conversión a `NULL` en almacenamiento                                             |
| Validación temporal | Marcaje de mediciones antiguas         | Umbrales 2h (antigua) / 24h (inactiva)                                            |
| Persistencia        | Idempotencia por llave natural         | SELECT previo + INSERT condicional (mediciones) / UPSERT (estaciones/pronósticos) |
| Resiliencia         | Manejo diferenciado de 404             | No reintentar 404 y desactivar estación especial (ej. 999)                        |
| Observabilidad      | Métricas en logs                       | Duración del ciclo, resumen de estados (activas, antiguas, inactivas, existentes) |

---

## 🕒 Scheduling Híbrido

Mecanismo: APScheduler en modo `BackgroundScheduler` con:

- `coalesce=True`: evita acumulación si hubo pausa.
- `max_instances=1`: nunca solapa el mismo job.
- `misfire_grace_time=30s`: tolera pequeños retrasos.

Jobs Activos:

1. `data_collection_job` (cada 10 min) → pronósticos + estaciones + barrido completo de mediciones.
2. `fast_measurements_job` (cada 30 s) → solo mediciones actuales (baja latencia para el mapa).
3. Bootstrap inmediato: ejecución completa al iniciar + primer incremento a los 5s.

Resultado: mapa fresco sin bloquear pronósticos y menor carga puntual sobre SIATA.

---

## 🧼 Estrategias de Limpieza & Normalización

| Aspecto               | Regla                                      | Motivo                                                     |
| --------------------- | ------------------------------------------ | ---------------------------------------------------------- |
| Valores sentinela     | `-999` → `NULL`                            | Evita outliers ficticios en promedios o coloración heatmap |
| Tiempo medición       | Epoch → `timestamp` naive (UTC almacenado) | Consistencia de queries y ordenación                       |
| Duplicados mediciones | (estación, timestamp) único                | Garantiza series limpias                                   |
| Estaciones 404        | Desactivación si persiste (ej. código 999) | Reduce ruido y reintentos inútiles                         |
| Campos desconocidos   | Default seguro o NULL                      | Evita fallos de parsing por cambios en API fuente          |

---

## �️ Modelo de Datos (Resumen Conceptual)

| Tabla         | Clave Natural                      | Notas                                                       |
| ------------- | ---------------------------------- | ----------------------------------------------------------- |
| `estaciones`  | `codigo`                           | Metadatos, `activa` se usa para el barrido incremental      |
| `pronosticos` | `zona + fecha`                     | Se actualiza campo `date_update` sin duplicar filas         |
| `mediciones`  | `estacion_codigo + date_timestamp` | Inserción idempotente; limpieza aplicada previo a persistir |

---

## 🔎 Observabilidad & Logging

Categorías de log:

- INFO: ciclo, conteos, resumen mediciones.
- DEBUG: granularidad por zona pronóstico y progreso incremental cada 25 estaciones.
- WARNING: reintentos, timestamps inválidos, 404.
- ERROR/EXCEPTION: fallos duros del job (sin abortar scheduler completo).

Tiempos: se loguea duración total del ciclo completo (promedio esperado < 15s).

---

## 🧩 Arquitectura Técnica

```
┌─────────────────────────┐      ┌───────────────────────┐
│       APScheduler       │      │        Frontend       │
│  (jobs 10m / 30s / boot)│      │  Single Page (Mapa +  │
└──────────┬──────────────┘      │  Pronósticos)         │
       │                     └──────────┬────────────┘
    llama funciones ETL                  consume
       │                                 │ JSON REST
┌──────────▼───────────┐   escribe   ┌───────▼───────────┐
│  data_collector.py   │────────────►│   PostgreSQL      │
│  (fetch + limpieza)  │             │ (persistencia)    │
└──────────┬───────────┘             └────────┬──────────┘
       │   expone /api                     │
    ┌────▼───────────┐                      consultas
    │   Flask API    │◄──────────────────────┘
    └────────────────┘
```

---

## � Frontend Destacado

| Componente       | Clave                | Detalle                                                 |
| ---------------- | -------------------- | ------------------------------------------------------- |
| Mapa Leaflet     | Heatmaps             | Temperatura y humedad con gradientes personalizados     |
| Markers modernos | Tooltips hover       | Chips de color según riqueza de datos (temp/hum/lluvia) |
| Pronósticos      | Etiquetas dinámicas  | “Hoy / Mañana” calculado contra fecha local             |
| Loader Global    | Secuencia orquestada | Estaciones → mediciones → pronósticos → render final    |
| Controles UX     | Toggle estaciones    | Limpieza de heatmap y estado textual activo             |

---

## � API (Backend)

| Endpoint                  | Método | Descripción                                          |
| ------------------------- | ------ | ---------------------------------------------------- |
| `/api/health`             | GET    | Estado simple del servicio                           |
| `/api/forecasts`          | GET    | Pronósticos de todas las zonas (últimos disponibles) |
| `/api/forecasts/<zona>`   | GET    | Pronósticos de una zona específica                   |
| `/api/stations`           | GET    | Listado estaciones (metadatos)                       |
| `/api/stations/all-data`  | GET    | Agregado: estaciones + última medición               |
| `/api/stations/<id>/data` | GET    | Mediciones crudas de una estación                    |

Respuestas estructuradas envolviendo `success`, `data` o `error`.

---

## ⚙️ Variables & Tuning

| Variable           | Default     | Uso                                  |
| ------------------ | ----------- | ------------------------------------ |
| `DATABASE_URL`     | (requerida) | Cadena conexión PostgreSQL           |
| `ETL_MAX_RETRIES`  | 3           | Reintentos HTTP (excepto 404)        |
| `ETL_BACKOFF_BASE` | 1.5         | Base exponencial (1, 1.5, 2.25…)     |
| `ETL_HTTP_TIMEOUT` | 30          | Timeout fetch pronósticos/estaciones |
| `LOG_LEVEL`        | INFO        | Verbosidad global                    |

Cambiar intervalos: editar `minutes=10` o `seconds=30` en `etl/scheduler.py`.

---

## 🚀 Ejecución Rápida (Docker Compose)

```powershell
docker-compose up --build
```

Servicios:

- Frontend: http://localhost
- Backend: http://localhost:5000/api/health
- PostgreSQL: localhost:5432

Rebuild más veloz en desarrollo backend:

```powershell
docker compose build backend --no-cache ; docker compose up backend -d
```

---

## �‍💻 Desarrollo Local (sin Docker)

Backend:

```powershell
cd backend
pip install -r requirements.txt
$env:DATABASE_URL="postgresql://user:pass@localhost:5432/benpo"  # ajustar
python app.py
```

Frontend (servidor simple):

```powershell
cd frontend
python -m http.server 8000
```

Navegar a: http://localhost:8000

---

## 🛠️ Troubleshooting Rápido

| Problema              | Causa probable                        | Acción                                 |
| --------------------- | ------------------------------------- | -------------------------------------- |
| Heatmap vacío         | Mediciones NULL / sin datos recientes | Ver logs `fast_measurements_job`       |
| Estación desaparece   | Marcada inactiva (>24h sin update)    | Confirmar en SIATA original            |
| Muchos WARNING 404    | Estación inválida (ej. 999)           | Ya se desactiva automáticamente        |
| Pronóstico sin Hoy    | API entregó días pasados              | Filtrado interno; revisar fecha server |
| Duplicados mediciones | (No debería)                          | Revisar constraint y SELECT previo     |

Logs detallados: ajustar `LOG_LEVEL=DEBUG`.

---

## 🧪 Calidad & Buenas Prácticas

- Idempotencia asegurada en inserciones críticas.
- Backoff exponencial evita golpear API en picos de error.
- Separación “full vs incremental” reduce latencia de visualización.
- Limpieza temprana evita propagar basura a capas superiores.
- Tooltips ligeros → mejor UX móvil.

---

## 🌱 Próximas Extensiones (Roadmap sugerido)

- Alertas push (umbrales de lluvia / temperatura).
- Agregaciones históricas (promedios horarios / diarios).
- Export CSV / Parquet de series de mediciones.
- Panel comparativo multi‑zona / multi‑variable.
- API de autenticación para endpoints avanzados.

---

## 🤝 Contribución

Proyecto académico orientado a exploración de ingestión meteorológica y visualización geoespacial. PRs con mejoras de observabilidad, caching o accesibilidad son bienvenidas.

---

## 📄 Licencia

Uso académico – Valle de Aburrá, Colombia 🇨🇴

---
