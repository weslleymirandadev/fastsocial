from fastapi import FastAPI, BackgroundTasks, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
import requests
import time
import logging

from datetime import datetime, timedelta
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Tuple, Union, Dict, Any

from automator.carousel import CarouselAutomator
from config import settings
from automator.logging_to_dbapi import DatabaseApiLogHandler

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Anexa o handler globalmente para todas as logs do backend (se ainda não anexado)
root_logger = logging.getLogger()
try:
    already = any(h.__class__.__name__ == "DatabaseApiLogHandler" for h in root_logger.handlers)
    if not already:
        db_handler = DatabaseApiLogHandler()
        db_handler.setLevel(logging.INFO)
        root_logger.addHandler(db_handler)
except Exception:
    # Não falha a inicialização do app caso haja problema ao anexar o handler
    pass

app = FastAPI(
    title="Backend API - Instagram Automation",
    version="2.1.0",
)

app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

# Variáveis globais para controle do loop
stop_event = threading.Event()
automation_thread = None


# === PROXY CRUD para database-api ===
@app.api_route("/proxy/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH"])
async def proxy(request: Request, path: str):
    url = f"{settings.DATABASE_API_URL}/{path.lstrip('/')}"
    if request.query_params:
        url += f"?{request.query_params}"
    try:
        resp = requests.request(
            method=request.method,
            url=url,
            headers={k: v for k, v in request.headers.items() if k.lower() != "host"},
            data=await request.body(),
            timeout=30,
        )
    except Exception as e:
        return JSONResponse(content={"error": "upstream request failed", "detail": str(e)}, status_code=502)

    # If upstream returned no content (e.g. 204 No Content), return an empty response with same status
    if resp.status_code == 204 or not resp.content:
        return Response(status_code=resp.status_code)

    # Try to parse JSON; if body is not JSON, return plain text
    try:
        data = resp.json()
    except ValueError:
        # Not JSON — return text body
        return JSONResponse(content={"text": resp.text}, status_code=resp.status_code)

    return JSONResponse(content=data, status_code=resp.status_code)


# === Configuração dinâmica ===
def get_rest_days() -> int:
    """Busca rest_days em /config/ na database-api.

    Usa valor padrão seguro (2) e garante mínimo de 1 dia.
    """
    default_days = 2
    days = default_days

    try:
        r_cfg = requests.get(f"{settings.DATABASE_API_URL}/config/")
        if r_cfg.status_code == 200:
            cfg = r_cfg.json() or {}
            if isinstance(cfg, dict) and "rest_days" in cfg:
                raw = cfg["rest_days"]
                if isinstance(raw, dict):
                    raw = raw.get("value")
                try:
                    if raw is not None:
                        days = int(raw)
                except (TypeError, ValueError):
                    pass
    except Exception:
        # Em caso de erro de rede/JSON, mantemos o default
        pass

    if days < 1:
        days = 1
    return days


def get_wait_config() -> tuple[int, int]:
    """Busca wait_min_seconds e wait_max_seconds na database-api.

    Garante defaults seguros (5, 15) e que min <= max.
    """
    default_min, default_max = 5, 15

    min_val = default_min
    max_val = default_max

    try:
        # /config/ retorna um objeto chave -> {value, description}
        r_cfg = requests.get(f"{settings.DATABASE_API_URL}/config/")
        if r_cfg.status_code == 200:
            cfg = r_cfg.json() or {}
            if isinstance(cfg, dict):
                # wait_min_seconds
                if "wait_min_seconds" in cfg:
                    raw = cfg["wait_min_seconds"]
                    if isinstance(raw, dict):
                        raw = raw.get("value")
                    try:
                        if raw is not None:
                            min_val = int(raw)
                    except (TypeError, ValueError):
                        pass

                # wait_max_seconds
                if "wait_max_seconds" in cfg:
                    raw = cfg["wait_max_seconds"]
                    if isinstance(raw, dict):
                        raw = raw.get("value")
                    try:
                        if raw is not None:
                            max_val = int(raw)
                    except (TypeError, ValueError):
                        pass
    except Exception:
        # Em caso de erro de rede ou JSON, mantemos os defaults
        pass

    # Sanitização básica
    if min_val < 1:
        min_val = 1
    if max_val < min_val:
        max_val = min_val

    return min_val, max_val


# === Loop Infinito com Descanso Individual ===
def run_forever():
    cycle = 0

    while not stop_event.is_set():
        cycle += 1
        stop_event.clear()  # garante que não pare no meio do ciclo
        start = datetime.utcnow()
        logger.info(f"══════ CICLO {cycle} INICIADO ══════ {start.strftime('%Y-%m-%d %H:%M:%S UTC')}")

        try:
            rest_days = get_rest_days()
            wait_min, wait_max = get_wait_config()
            automator = CarouselAutomator(
                rest_days=rest_days,
                wait_min_seconds=wait_min,
                wait_max_seconds=wait_max,
            )
            automator.run()  # ← agora recebe o parâmetro de descanso
        except Exception as e:
            logger.error(f"Erro crítico no ciclo {cycle}: {e}", exc_info=True)

        end = datetime.utcnow()
        logger.info(f"══════ CICLO {cycle} FINALIZADO ══════ {end.strftime('%H:%M:%S')} | Duração: {(end-start).seconds}s")

        if stop_event.is_set():
            logger.info("Comando de parada recebido. Encerrando após ciclo completo.")
            break

        # Pequena pausa antes de iniciar novo ciclo (evita sobrecarga)
        time.sleep(30)

    logger.info("LOOP ENCERRADO COM SUCESSO.")


# === Rotas de Controle ===
@app.post("/start/")
def start_automation(background_tasks: BackgroundTasks):
    global automation_thread
    if automation_thread and automation_thread.is_alive():
        return {"status": "Já está rodando!"}

    stop_event.clear()
    automation_thread = threading.Thread(target=run_forever, daemon=True)
    automation_thread.start()
    return {"status": "Automação iniciada em loop infinito", "dica": "Use POST /stop/ para parar"}


@app.post("/stop-immediate/")
def stop_immediate():
    """Para imediatamente a execução, mesmo no meio de um ciclo."""
    if not automation_thread or not automation_thread.is_alive():
        return {"status": "Nenhum loop ativo"}

    logger.warning("Comando /stop-immediate recebido → parando execução IMEDIATAMENTE")
    
    # Sinaliza para parar
    stop_event.set()
    
    # Tenta encerrar a thread imediatamente
    try:
        # Isso pode causar problemas se a thread estiver em operação crítica
        # mas é o que precisamos para parar imediatamente
        if automation_thread.is_alive():
            import ctypes
            import inspect
            
            # Obtém o ID da thread
            thread_id = automation_thread.ident
            
            # Envia uma exceção para a thread para forçar a parada
            res = ctypes.pythonapi.PyThreadState_SetAsyncExc(
                ctypes.c_long(thread_id),
                ctypes.py_object(SystemExit)
            )
            
            if res == 0:
                logger.error("Falha ao interromper a thread: thread não encontrada")
            elif res > 1:
                # Se retornar > 1, precisamos chamar novamente para restaurar o estado
                ctypes.pythonapi.PyThreadState_SetAsyncExc(ctypes.c_long(thread_id), None)
                logger.warning("Thread interrompida com sucesso (forçado)")
            
    except Exception as e:
        logger.error(f"Erro ao tentar parar a thread: {e}")
        return {"status": "erro", "detail": f"Erro ao parar a thread: {str(e)}"}
    
    return {"status": "Parada imediata solicitada", "detail": "A execução foi interrompida imediatamente"}


@app.get("/")
def health():
    return {
        "status": "Backend ativo",
        "loop_running": automation_thread.is_alive() if automation_thread else False,
        "controles": {
            "iniciar": "POST /start/",
            "parar": "POST /stop/",
            "config_rest_days": "PUT /proxy/config/rest_days → valor em dias inteiros",
            "set_config_bulk": "POST /config/bulk (JSON key->value or key->{value,description})"
        }
    }


@app.post("/config/bulk")
async def set_config_bulk(request: Request):
    """Convenience endpoint: forwards a bulk config JSON to the database-api.

    Accepts JSON object mapping keys to either a string value or an object {value, description}.
    """
    try:
        payload = await request.json()
    except Exception as e:
        return JSONResponse({"error": "invalid json", "detail": str(e)}, status_code=400)

    try:
        resp = requests.post(f"{settings.DATABASE_API_URL}/config/bulk", json=payload, timeout=15)
    except Exception as e:
        return JSONResponse({"error": "upstream request failed", "detail": str(e)}, status_code=502)

    if resp.status_code == 204 or not resp.content:
        return Response(status_code=resp.status_code)

    try:
        data = resp.json()
    except ValueError:
        return JSONResponse({"text": resp.text}, status_code=resp.status_code)

    return JSONResponse(content=data, status_code=resp.status_code)


# === Bulk endpoints (frontend chama aqui; este backend chama a database-api em paralelo) ===

def _post_to_database(path: str, json_body: Dict[str, Any], timeout: float = 15.0) -> Tuple[int, Union[Dict[str, Any], str]]:
    """Helper síncrono para POST na database-api, retornando (status_code, body/json ou texto)."""
    url = f"{settings.DATABASE_API_URL}/{path.lstrip('/') }"
    try:
        resp = requests.post(url, json=json_body, timeout=timeout)
    except Exception as e:
        return 502, {"error": "upstream request failed", "detail": str(e)}

    try:
        return resp.status_code, resp.json()
    except ValueError:
        return resp.status_code, resp.text


@app.post("/restaurants/bulk")
async def bulk_create_restaurants(request: Request):
    """Recebe uma lista de restaurantes e cria cada um na database-api em paralelo.

    A lógica de validação/deduplicação continua na database-api (RestaurantCreate + POST /restaurants/).
    """
    try:
        payload = await request.json()
    except Exception as e:
        return JSONResponse({"error": "invalid json", "detail": str(e)}, status_code=400)

    if not isinstance(payload, list):
        return JSONResponse({"error": "payload must be a JSON array"}, status_code=400)

    results = []
    errors = []

    with ThreadPoolExecutor(max_workers=100) as executor:
        future_map = {
            executor.submit(_post_to_database, "restaurants/", item): i
            for i, item in enumerate(payload)
        }
        for future in as_completed(future_map):
            idx = future_map[future]
            try:
                status, body = future.result()
            except Exception as e:  # segurança extra
                errors.append({"index": idx, "error": str(e)})
                continue

            if 200 <= status < 300:
                results.append(body)
            else:
                errors.append({"index": idx, "status": status, "body": body})

    return {"created": results, "errors": errors}


@app.post("/personas/bulk")
async def bulk_create_personas(request: Request):
    """Recebe uma lista de personas e cria cada uma na database-api em paralelo."""
    try:
        payload = await request.json()
    except Exception as e:
        return JSONResponse({"error": "invalid json", "detail": str(e)}, status_code=400)

    if not isinstance(payload, list):
        return JSONResponse({"error": "payload must be a JSON array"}, status_code=400)

    results = []
    errors = []

    with ThreadPoolExecutor(max_workers=100) as executor:
        future_map = {
            executor.submit(_post_to_database, "personas/", item): i
            for i, item in enumerate(payload)
        }
        for future in as_completed(future_map):
            idx = future_map[future]
            try:
                status, body = future.result()
            except Exception as e:
                errors.append({"index": idx, "error": str(e)})
                continue

            if 200 <= status < 300:
                results.append(body)
            else:
                errors.append({"index": idx, "status": status, "body": body})

    return {"created": results, "errors": errors}


@app.post("/phrases/bulk")
async def bulk_create_phrases(request: Request):
    """Recebe uma lista de frases e cria cada uma na database-api em paralelo."""
    try:
        payload = await request.json()
    except Exception as e:
        return JSONResponse({"error": "invalid json", "detail": str(e)}, status_code=400)

    if not isinstance(payload, list):
        return JSONResponse({"error": "payload must be a JSON array"}, status_code=400)

    results = []
    errors = []

    with ThreadPoolExecutor(max_workers=100) as executor:
        future_map = {
            executor.submit(_post_to_database, "phrases/", item): i
            for i, item in enumerate(payload)
        }
        for future in as_completed(future_map):
            idx = future_map[future]
            try:
                status, body = future.result()
            except Exception as e:
                errors.append({"index": idx, "error": str(e)})
                continue

            if 200 <= status < 300:
                results.append(body)
            else:
                errors.append({"index": idx, "status": status, "body": body})

    return {"created": results, "errors": errors}