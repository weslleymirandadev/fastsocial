from fastapi import FastAPI, BackgroundTasks, HTTPException, Request, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response, FileResponse

import requests
import time
import logging

from datetime import datetime, timedelta, timezone

import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Tuple, Union, Dict, Any

from automator.carousel import CarouselAutomator
from config import settings
from automator.logging_to_dbapi import DatabaseApiLogHandler
from restaurant_processor import process_restaurants_excel, process_restaurants_csv, assign_blocks_to_restaurants

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


@app.get("/reports/messages.xlsx")
async def proxy_messages_report(request: Request):
    """Proxy para o relatório XLSX de mensagens na database-api.

    Preserva o conteúdo XLSX para o frontend baixar diretamente.
    """
    url = f"{settings.DATABASE_API_URL}/reports/messages.xlsx"
    try:
        resp = requests.get(url, params=dict(request.query_params), timeout=60)
    except Exception as e:
        return JSONResponse(content={"error": "upstream request failed", "detail": str(e)}, status_code=502)

    return Response(
        content=resp.content,
        media_type=resp.headers.get(
            "content-type",
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        ),
        status_code=resp.status_code,
        headers={
            "Content-Disposition": resp.headers.get(
                "content-disposition", "attachment; filename=messages_report.xlsx"
            )
        },
    )


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
    BRT = timezone(timedelta(hours=-3))

    while not stop_event.is_set():
        cycle += 1
        stop_event.clear()  # garante que não pare no meio do ciclo
        start = datetime.now(BRT)
        logger.info(f"══════ CICLO {cycle} INICIADO ══════")

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

        end = datetime.now(BRT)
        logger.info(f"══════ CICLO {cycle} FINALIZADO ══════ {end.strftime('%H:%M:%S')} | Duração: {(end-start).seconds}s")

        if stop_event.is_set():
            logger.info("Comando de parada recebido. Encerrando após ciclo completo.")
            break

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


@app.post("/restaurants/process-excel")
async def process_restaurants_excel_endpoint(file: UploadFile = File(...)):
    """
    Processa arquivo Excel de restaurantes com deduplicação conservadora e agrupamento inteligente.
    
    Recebe um arquivo Excel com a aba "Restaurantes" e retorna um arquivo processado com:
    - Deduplicação por Instagram idêntico ou Endereço Estrito
    - Agrupamento em clusters (mesmo grupo/rede/dono)
    - Distribuição em blocos de 5 a 10 registros
    - Auditorias completas de deduplicação e clusters
    """
    import tempfile
    import os
    from pathlib import Path
    
    if not file.filename.lower().endswith((".xlsx", ".xls", ".csv")):
        return JSONResponse(
            {"error": "Arquivo deve ser Excel (.xlsx/.xls) ou CSV (.csv)"}, 
            status_code=400
        )
    
    # Salva arquivo temporário
    suffix = ".csv" if file.filename.lower().endswith(".csv") else ".xlsx"
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp_input:
        content = await file.read()
        tmp_input.write(content)
        tmp_input_path = tmp_input.name
    
    try:
        # Processa o arquivo
        if file.filename.lower().endswith(".csv"):
            result = process_restaurants_csv(tmp_input_path)
        else:
            result = process_restaurants_excel(tmp_input_path)
        output_path = result['output_file']
        
        # Retorna o arquivo processado
        return FileResponse(
            output_path,
            media_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
            filename=Path(output_path).name,
            headers={
                "Content-Disposition": f"attachment; filename={Path(output_path).name}"
            }
        )
    except Exception as e:
        logger.error(f"Erro ao processar Excel: {e}", exc_info=True)
        return JSONResponse(
            {"error": "Erro ao processar arquivo", "detail": str(e)}, 
            status_code=500
        )
    finally:
        # Remove arquivo temporário de entrada
        try:
            os.unlink(tmp_input_path)
        except:
            pass


@app.post("/restaurants/bulk")
async def bulk_create_restaurants(request: Request):
    """Recebe uma lista de restaurantes e cria em batches usando o endpoint bulk da database-api.

    ATRIBUIÇÃO AUTOMÁTICA DE BLOCOS:
    - Se os restaurantes não tiverem blocos, atribui automaticamente usando a lógica de agrupamento
    - Se alguns tiverem blocos e outros não, atribui apenas aos que não têm
    - Sempre usa a lógica de agrupamento para garantir que clusters sejam separados em blocos distintos
    
    Processa em lotes de 100 restaurantes por vez para evitar sobrecarga do banco de dados.
    """
    try:
        payload = await request.json()
    except Exception as e:
        return JSONResponse({"error": "invalid json", "detail": str(e)}, status_code=400)

    if not isinstance(payload, list):
        return JSONResponse({"error": "payload must be a JSON array"}, status_code=400)

    if not payload:
        return {"created": 0, "skipped": 0, "created_items": [], "errors": []}

    # Verifica se os restaurantes têm blocos atribuídos
    has_blocks = any(
        r.get("bloco") is not None and r.get("bloco") != "" 
        for r in payload 
        if isinstance(r, dict)
    )
    
    # Se não tiverem blocos ou se alguns não tiverem, atribui automaticamente
    if not has_blocks or any(
        r.get("bloco") is None or r.get("bloco") == "" 
        for r in payload 
        if isinstance(r, dict)
    ):
        try:
            logger.info(f"Atribuindo blocos automaticamente a {len(payload)} restaurantes...")
            # Busca o maior bloco existente no banco para continuar a numeração
            try:
                resp_existing = requests.get(f"{settings.DATABASE_API_URL}/restaurants/", timeout=10)
                if resp_existing.status_code == 200:
                    existing_restaurants = resp_existing.json()
                    max_existing_bloco = max(
                        (r.get("bloco", 0) or 0 for r in existing_restaurants if r.get("bloco")),
                        default=0
                    )
                    start_block_num = max_existing_bloco + 1
                else:
                    start_block_num = 1
            except Exception as e:
                logger.warning(f"Erro ao buscar restaurantes existentes para determinar bloco inicial: {e}")
                start_block_num = 1
            
            # Atribui blocos usando a lógica de agrupamento
            payload = assign_blocks_to_restaurants(payload, start_block_num=start_block_num)
            logger.info(f"Blocos atribuídos automaticamente. Maior bloco: {max((r.get('bloco', 0) or 0) for r in payload) if payload else 0}")
        except Exception as e:
            logger.error(f"Erro ao atribuir blocos automaticamente: {e}", exc_info=True)
            # Continua mesmo se falhar a atribuição de blocos (não bloqueia o processo)

    BATCH_SIZE = 100  # Processa 100 restaurantes por vez
    all_created = []
    all_skipped = 0
    errors = []

    # Processa em batches
    for i in range(0, len(payload), BATCH_SIZE):
        batch = payload[i:i + BATCH_SIZE]
        try:
            url = f"{settings.DATABASE_API_URL}/restaurants/bulk"
            resp = requests.post(url, json=batch, timeout=60)  # Timeout maior para batches
            
            if resp.status_code == 201:
                result = resp.json()
                all_created.extend(result.get("created_items", []))
                all_skipped += result.get("skipped", 0)
            else:
                # Se o batch falhar, tenta processar item por item para identificar erros específicos
                try:
                    error_detail = resp.json()
                except:
                    error_detail = resp.text
                errors.append({
                    "batch_start": i,
                    "batch_end": min(i + BATCH_SIZE, len(payload)),
                    "status": resp.status_code,
                    "detail": error_detail
                })
        except Exception as e:
            errors.append({
                "batch_start": i,
                "batch_end": min(i + BATCH_SIZE, len(payload)),
                "error": str(e)
            })

    return {
        "created": len(all_created),
        "skipped": all_skipped,
        "created_items": all_created,
        "errors": errors
    }


@app.post("/personas/bulk")
async def bulk_create_personas(request: Request):
    """Recebe uma lista de personas e cria em batches usando o endpoint bulk da database-api.

    Processa em lotes de 100 personas por vez para evitar sobrecarga do banco de dados.
    """
    try:
        payload = await request.json()
    except Exception as e:
        return JSONResponse({"error": "invalid json", "detail": str(e)}, status_code=400)

    if not isinstance(payload, list):
        return JSONResponse({"error": "payload must be a JSON array"}, status_code=400)

    if not payload:
        return {"created": 0, "skipped": 0, "created_items": [], "errors": []}

    BATCH_SIZE = 100  # Processa 100 personas por vez
    all_created = []
    all_skipped = 0
    errors = []

    # Processa em batches
    for i in range(0, len(payload), BATCH_SIZE):
        batch = payload[i:i + BATCH_SIZE]
        try:
            url = f"{settings.DATABASE_API_URL}/personas/bulk"
            resp = requests.post(url, json=batch, timeout=60)  # Timeout maior para batches
            
            if resp.status_code == 201:
                result = resp.json()
                all_created.extend(result.get("created_items", []))
                all_skipped += result.get("skipped", 0)
            else:
                # Se o batch falhar, registra o erro
                try:
                    error_detail = resp.json()
                except:
                    error_detail = resp.text
                errors.append({
                    "batch_start": i,
                    "batch_end": min(i + BATCH_SIZE, len(payload)),
                    "status": resp.status_code,
                    "detail": error_detail
                })
        except Exception as e:
            errors.append({
                "batch_start": i,
                "batch_end": min(i + BATCH_SIZE, len(payload)),
                "error": str(e)
            })

    return {
        "created": len(all_created),
        "skipped": all_skipped,
        "created_items": all_created,
        "errors": errors
    }


@app.post("/phrases/bulk")
async def bulk_create_phrases(request: Request):
    """Recebe uma lista de frases e cria em batches usando o endpoint bulk da database-api.

    Processa em lotes de 100 frases por vez para evitar sobrecarga do banco de dados.
    """
    try:
        payload = await request.json()
    except Exception as e:
        return JSONResponse({"error": "invalid json", "detail": str(e)}, status_code=400)

    if not isinstance(payload, list):
        return JSONResponse({"error": "payload must be a JSON array"}, status_code=400)

    if not payload:
        return {"created": 0, "skipped": 0, "created_items": [], "errors": []}

    BATCH_SIZE = 100  # Processa 100 frases por vez
    all_created = []
    all_skipped = 0
    errors = []

    # Processa em batches
    for i in range(0, len(payload), BATCH_SIZE):
        batch = payload[i:i + BATCH_SIZE]
        try:
            url = f"{settings.DATABASE_API_URL}/phrases/bulk"
            resp = requests.post(url, json=batch, timeout=60)  # Timeout maior para batches
            
            if resp.status_code == 201:
                result = resp.json()
                all_created.extend(result.get("created_items", []))
                all_skipped += result.get("skipped", 0)
            else:
                # Se o batch falhar, registra o erro
                try:
                    error_detail = resp.json()
                except:
                    error_detail = resp.text
                errors.append({
                    "batch_start": i,
                    "batch_end": min(i + BATCH_SIZE, len(payload)),
                    "status": resp.status_code,
                    "detail": error_detail
                })
        except Exception as e:
            errors.append({
                "batch_start": i,
                "batch_end": min(i + BATCH_SIZE, len(payload)),
                "error": str(e)
            })

    return {
        "created": len(all_created),
        "skipped": all_skipped,
        "created_items": all_created,
        "errors": errors
    }