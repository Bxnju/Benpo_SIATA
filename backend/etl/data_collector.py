import requests
import json
from datetime import datetime, timedelta, timezone
from database.db_manager import get_db_cursor
import logging
import time
import os

logger = logging.getLogger("etl.data_collector")

# URLs SIATA
WRF_BASE_URL = "https://siata.gov.co/data/siata_app/"
ESTACIONES_URL = "https://siata.gov.co/data/siata_app/PluviometricaMeteo.json"

WRF_ZONES = [
    'sabaneta', 'palmitas', 'medOriente', 'medOccidente',
    'medCentro', 'laestrella', 'itagui', 'girardota',
    'envigado', 'copacabana', 'caldas', 'bello', 'barbosa'
]

# Zona horaria de Colombia (UTC-5)
COLOMBIA_TZ = timezone(timedelta(hours=-5))

# Configuración reintentos
MAX_RETRIES = int(os.getenv("ETL_MAX_RETRIES", 3))
BACKOFF_BASE = float(os.getenv("ETL_BACKOFF_BASE", 1.5))
TIMEOUT = int(os.getenv("ETL_HTTP_TIMEOUT", 30))


def http_get_json(url, timeout=TIMEOUT):
    """Wrapper con reintentos exponenciales y logging"""
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            resp = requests.get(url, timeout=timeout)
            if resp.status_code == 404:
                # No reintentar en 404
                resp.raise_for_status()
            resp.raise_for_status()
            return resp.json()
        except requests.HTTPError as e:
            if isinstance(e, requests.HTTPError) and getattr(e.response, 'status_code', None) == 404:
                logger.warning(f"404 fijo {url} no se reintenta")
                raise
            wait = BACKOFF_BASE ** (attempt - 1)
            logger.warning(f"Fallo request {url} intento {attempt}/{MAX_RETRIES}: {e}")
            if attempt == MAX_RETRIES:
                raise
            time.sleep(wait)
        except (requests.RequestException, json.JSONDecodeError) as e:
            wait = BACKOFF_BASE ** (attempt - 1)
            logger.warning(f"Fallo request {url} intento {attempt}/{MAX_RETRIES}: {e}")
            if attempt == MAX_RETRIES:
                raise
            time.sleep(wait)


def collect_all_data():
    """Recolectar todos los datos: pronósticos, estaciones y mediciones"""
    inicio = datetime.utcnow()
    logger.info(f"Iniciando recolección de datos UTC={inicio.isoformat()} COL={datetime.now(tz=COLOMBIA_TZ)}")
    try:
        collect_wrf_forecasts()
        collect_estaciones()
        collect_mediciones()
        logger.info("Recolección completa OK")
    except Exception:
        logger.exception("Fallo en ciclo completo de recolección")
    finally:
        dur = (datetime.utcnow() - inicio).total_seconds()
        logger.info(f"Duración ciclo ETL: {dur:.2f}s")


def collect_wrf_forecasts():
    """Recolectar pronósticos WRF de todas las zonas"""
    logger.info("Recolectando pronósticos WRF")
    for zona in WRF_ZONES:
        url = f"{WRF_BASE_URL}wrf{zona}.json"
        try:
            data = http_get_json(url)
            logger.debug(f"Zona {zona} date={data.get('date')} pronosticos={len(data.get('pronostico', []))}")
            save_wrf_forecast(zona, data)
        except Exception as e:
            logger.error(f"Error zona {zona}: {e}")


def collect_estaciones():
    """Recolectar información de estaciones activas"""
    logger.info("Recolectando estaciones")
    try:
        data = http_get_json(ESTACIONES_URL)
        estaciones = data.get('estaciones', [])
        logger.info(f"Total estaciones recibidas={len(estaciones)} red={data.get('red', 'N/A')}")
        with get_db_cursor() as cursor:
            for estacion in estaciones:
                cursor.execute("""
                    INSERT INTO estaciones (
                        codigo, nombre, latitud, longitud, ciudad,
                        comuna, subcuenca, barrio, valor, red, activa
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (codigo) DO UPDATE SET
                        nombre = EXCLUDED.nombre,
                        latitud = EXCLUDED.latitud,
                        longitud = EXCLUDED.longitud,
                        ciudad = EXCLUDED.ciudad,
                        comuna = EXCLUDED.comuna,
                        subcuenca = EXCLUDED.subcuenca,
                        barrio = EXCLUDED.barrio,
                        valor = EXCLUDED.valor,
                        red = EXCLUDED.red,
                        activa = true,
                        updated_at = CURRENT_TIMESTAMP
                """, (
                    estacion.get('codigo'),
                    estacion.get('nombre', ''),
                    estacion.get('latitud'),
                    estacion.get('longitud'),
                    estacion.get('ciudad', ''),
                    estacion.get('comuna', ''),
                    estacion.get('subcuenca', ''),
                    estacion.get('barrio', ''),
                    estacion.get('valor', 0),
                    data.get('red', 'meteo'),
                    True
                ))
        logger.info("Estaciones actualizadas en DB")
    except Exception:
        logger.exception("Error recolectando estaciones")


def collect_mediciones():
    """Recolectar mediciones de todas las estaciones activas"""
    logger.info("Recolectando mediciones")
    try:
        with get_db_cursor() as cursor:
            cursor.execute("SELECT codigo FROM estaciones WHERE activa = true")
            estaciones = cursor.fetchall()
        logger.info(f"Estaciones activas a procesar={len(estaciones)}")

        resumen = {"activas": 0, "antiguas": 0, "inactivas": 0, "mediciones": 0, "existentes": 0}

        for idx, est in enumerate(estaciones):
            if idx and idx % 25 == 0:
                logger.debug(f"Progreso {idx}/{len(estaciones)}")
            estado = collect_medicion_estacion(est['codigo'])
            if estado in resumen:
                resumen[estado] += 1
            elif estado == 'activa':
                resumen['activas'] += 1
                resumen['mediciones'] += 1
            elif estado == 'existente':
                resumen['existentes'] += 1

        logger.info(f"Resumen mediciones: {resumen}")
    except Exception:
        logger.exception("Error general en mediciones")


def collect_medicion_estacion(codigo_estacion):
    """Recolectar medición de una estación específica"""
    try:
        url = f"{WRF_BASE_URL}{codigo_estacion}.json"
        try:
            data = http_get_json(url, timeout=10)
        except requests.HTTPError as http_err:
            if getattr(http_err.response, 'status_code', None) == 404:
                # Desactivar estación inexistente (ej. 999) para no consultarla de nuevo
                if codigo_estacion == 999:
                    with get_db_cursor() as cursor:
                        cursor.execute("UPDATE estaciones SET activa=false WHERE codigo=%s", (codigo_estacion,))
                        logger.info(f"Estación {codigo_estacion} desactivada por 404 persistente")
                return 'inactiva'
            return 'error'
        date_raw = data.get('date', '0').strip()
        try:
            date_timestamp = int(float(date_raw))
        except (ValueError, TypeError):
            logger.warning(f"Timestamp inválido estacion={codigo_estacion} raw={date_raw}")
            return 'error'

        fecha_medicion_utc = datetime.fromtimestamp(date_timestamp, tz=timezone.utc)
        now_colombia = datetime.now(tz=COLOMBIA_TZ)
        diferencia_horas = (now_colombia.replace(tzinfo=None) - fecha_medicion_utc.replace(tzinfo=None)).total_seconds() / 3600

        if diferencia_horas > 24:
            return 'inactiva'
        if diferencia_horas > 2:
            return 'antigua'

        def clean_value(value):
            try:
                val = float(value)
                return None if val == -999 or val < -900 else val
            except (ValueError, TypeError):
                return None

        datos_limpios = {k: clean_value(data.get(k)) for k in ['t', 'h', 'p', 'ws', 'wd', 'p10m', 'p1h', 'p24h']}

        with get_db_cursor() as cursor:
            cursor.execute("""
                SELECT id FROM mediciones
                WHERE estacion_codigo = %s AND date_timestamp = %s
            """, (codigo_estacion, date_timestamp))
            if cursor.fetchone():
                return 'existente'

            cursor.execute("""
                INSERT INTO mediciones (
                    estacion_codigo, date_timestamp, fecha_medicion,
                    t, h, p, ws, wd, p10m, p1h, p24h, is_valid
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """, (
                codigo_estacion,
                date_timestamp,
                fecha_medicion_utc.replace(tzinfo=None),
                datos_limpios['t'], datos_limpios['h'], datos_limpios['p'],
                datos_limpios['ws'], datos_limpios['wd'], datos_limpios['p10m'],
                datos_limpios['p1h'], datos_limpios['p24h'], True
            ))
        return 'activa'
    except requests.RequestException:
        return 'error_conexion'
    except Exception as e:
        logger.error(f"Error en estación {codigo_estacion}: {e}")
        return 'error'


def save_wrf_forecast(zona, data):
    """Guardar pronóstico WRF en la base de datos"""
    try:
        with get_db_cursor() as cursor:
            date_update = data.get('date', '')
            pronosticos = data.get('pronostico', [])
            guardados = 0
            actualizados = 0
            for pronostico in pronosticos:
                cursor.execute("""
                    SELECT id FROM pronosticos
                    WHERE zona = %s AND fecha = %s
                """, (zona, pronostico.get('fecha')))
                existing = cursor.fetchone()
                if existing:
                    cursor.execute("""
                        UPDATE pronosticos SET
                            date_update = %s,
                            temperatura_maxima = %s,
                            temperatura_minima = %s,
                            lluvia_madrugada = %s,
                            lluvia_mannana = %s,
                            lluvia_tarde = %s,
                            lluvia_noche = %s
                        WHERE id = %s
                    """, (
                        date_update,
                        int(pronostico.get('temperatura_maxima', 0)),
                        int(pronostico.get('temperatura_minima', 0)),
                        pronostico.get('lluvia_madrugada', ''),
                        pronostico.get('lluvia_mannana', ''),
                        pronostico.get('lluvia_tarde', ''),
                        pronostico.get('lluvia_noche', ''),
                        existing['id']
                    ))
                    actualizados += 1
                else:
                    cursor.execute("""
                        INSERT INTO pronosticos (
                            zona, date_update, fecha, temperatura_maxima,
                            temperatura_minima, lluvia_madrugada, lluvia_mannana,
                            lluvia_tarde, lluvia_noche
                        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """, (
                        zona,
                        date_update,
                        pronostico.get('fecha'),
                        int(pronostico.get('temperatura_maxima', 0)),
                        int(pronostico.get('temperatura_minima', 0)),
                        pronostico.get('lluvia_madrugada', ''),
                        pronostico.get('lluvia_mannana', ''),
                        pronostico.get('lluvia_tarde', ''),
                        pronostico.get('lluvia_noche', '')
                    ))
                    guardados += 1
        logger.debug(f"Zona {zona}: nuevos={guardados} actualizados={actualizados}")
    except Exception:
        logger.exception(f"Error guardando pronóstico zona {zona}")
        raise