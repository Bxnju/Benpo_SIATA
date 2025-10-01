from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.executors.pool import ThreadPoolExecutor
from apscheduler.jobstores.memory import MemoryJobStore
from .data_collector import collect_all_data, collect_mediciones
import atexit
import logging

logger = logging.getLogger("etl.scheduler")

scheduler = None

def _safe_collect():
    try:
        logger.info("Ejecutando job collect_all_data")
        collect_all_data()
        logger.info("Job collect_all_data finalizado")
    except Exception:
        logger.exception("Error en job collect_all_data")


def _safe_collect_mediciones():
    try:
        logger.debug("Ejecutando job rápido collect_mediciones (30s)")
        collect_mediciones()
    except Exception:
        logger.exception("Error en job rápido mediciones")


def start_scheduler():
    global scheduler
    if scheduler and scheduler.running:
        logger.info("Scheduler ya estaba en ejecución")
        return scheduler

    jobstores = {
        'default': MemoryJobStore()
    }
    executors = {
        'default': ThreadPoolExecutor(8)
    }
    job_defaults = {
        'coalesce': True,          # Combinar ejecuciones acumuladas
        'max_instances': 1,        # Evitar solapamientos
        'misfire_grace_time': 30   # Tolerancia a retrasos (segundos)
    }

    scheduler = BackgroundScheduler(jobstores=jobstores, executors=executors, job_defaults=job_defaults, timezone='UTC')

    # Job completo cada 10 minutos
    scheduler.add_job(
        func=_safe_collect,
        trigger="interval",
        minutes=10,
        id='data_collection_job',
        replace_existing=True
    )

    # Job rápido de mediciones cada 30 segundos
    scheduler.add_job(
        func=_safe_collect_mediciones,
        trigger="interval",
        seconds=30,
        id='fast_measurements_job',
        replace_existing=True
    )

    # Primera ejecución completa inmediata
    _safe_collect()

    # Iniciar mediciones rápido después de 5s (add_date job)
    from datetime import datetime, timedelta
    scheduler.add_job(
        func=_safe_collect_mediciones,
        trigger='date',
        run_date=datetime.utcnow() + timedelta(seconds=5),
        id='fast_measurements_initial',
        replace_existing=True
    )

    scheduler.start()
    logger.info("✅ Scheduler iniciado (ETL 10min + mediciones cada 30s)")

    atexit.register(_shutdown)
    return scheduler


def _shutdown():
    global scheduler
    if scheduler and scheduler.running:
        try:
            scheduler.shutdown()
            logger.info("Scheduler detenido correctamente")
        except Exception:
            logger.exception("Error al detener scheduler")