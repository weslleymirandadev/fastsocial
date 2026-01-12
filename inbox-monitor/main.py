import logging
import threading
import requests
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
try:
    from .inbox_monitor import InboxMonitor
    from .config import settings
except ImportError:
    # Para execução direta
    from inbox_monitor import InboxMonitor
    from config import settings

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Estado global
monitor: InboxMonitor = None
monitor_thread: threading.Thread = None


def _get_personas_count() -> int:
    """Busca o número de personas na database-api."""
    try:
        db_url = settings.DATABASE_API_URL.rstrip("/")
        resp = requests.get(f"{db_url}/personas/", timeout=5)
        resp.raise_for_status()
        personas = resp.json()
        return len(personas)
    except Exception as e:
        logger.warning(f"Erro ao buscar personas: {e}")
        return 0


def start_monitoring_background():
    """Inicia o monitoramento em background."""
    global monitor, monitor_thread
    
    logger.info("Iniciando monitoramento automático do inbox...")
    
    # Cria o monitor (ele busca personas automaticamente da database-api)
    monitor = InboxMonitor(
        check_interval=settings.CHECK_INTERVAL_SECONDS
    )
    
    # Inicia em thread separada (daemon=True para parar quando a aplicação encerrar)
    monitor_thread = threading.Thread(target=monitor.start_monitoring, daemon=True)
    monitor_thread.start()
    
    logger.info("Monitoramento iniciado automaticamente")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Gerencia o ciclo de vida da aplicação - inicia monitoramento ao subir."""
    # Startup: inicia monitoramento
    start_monitoring_background()
    yield
    # Shutdown: para monitoramento (se necessário)
    if monitor:
        logger.info("Parando monitoramento...")
        monitor.stop_monitoring()


app = FastAPI(
    title="Instagram Inbox Monitor API",
    lifespan=lifespan
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
def root():
    """Retorna status da API e do monitoramento."""
    personas_count = _get_personas_count()
    is_running = monitor is not None and monitor.running if monitor else False
    
    return {
        "message": "Instagram Inbox Monitor API",
        "status": "running",
        "monitoring": is_running,
        "personas_count": personas_count,
        "check_interval": settings.CHECK_INTERVAL_SECONDS,
        "database_api_url": settings.DATABASE_API_URL
    }


@app.get("/status")
def get_status():
    """Retorna informações detalhadas sobre o status do monitoramento."""
    personas_count = _get_personas_count()
    is_running = monitor is not None and monitor.running if monitor else False
    
    return {
        "running": is_running,
        "personas_count": personas_count,
        "check_interval": settings.CHECK_INTERVAL_SECONDS,
        "database_api_url": settings.DATABASE_API_URL,
        "message": "Monitoramento automático ativo" if is_running else "Monitoramento não está rodando"
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8081)
