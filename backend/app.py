from flask import Flask
from flask_cors import CORS
from api.routes import api
import logging
from etl.scheduler import start_scheduler

# Configurar logging (INFO por defecto, permitir override con env LOG_LEVEL)
logging.basicConfig(level=logging.getLevelName(
    (lambda lvl: lvl if lvl in logging._nameToLevel else 'INFO')(  # noqa: E501
        __import__('os').getenv('LOG_LEVEL', 'INFO').upper()
    )
), format='%(asctime)s - %(levelname)s - %(name)s - %(message)s')
logger = logging.getLogger("app")

app = Flask(__name__)
CORS(app)

# Registrar blueprints
app.register_blueprint(api, url_prefix='/api')

# Iniciar scheduler (lazy para evitar doble arranque en reloader)
_scheduler_started = False

def ensure_scheduler():
    global _scheduler_started
    if not _scheduler_started:
        try:
            start_scheduler()
            _scheduler_started = True
            logger.info("Scheduler ETL iniciado")
        except Exception as e:
            logger.exception(f"No se pudo iniciar el scheduler: {e}")

@app.route('/')
def index():
    # Garantizar scheduler activo incluso si este endpoint es el primero en recibir tráfico
    ensure_scheduler()
    return {'message': 'SIATA Data API', 'status': 'running'}

if __name__ == '__main__':
    ensure_scheduler()
    app.run(host='0.0.0.0', port=5000, debug=True)