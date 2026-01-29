from fastapi import FastAPI, HTTPException, Depends, WebSocket, WebSocketDisconnect
from fastapi.responses import Response

from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
from typing import List, Optional
from sqlalchemy import func
import asyncio
from collections import deque
import csv
import io
from datetime import datetime, timedelta
from openpyxl import Workbook

from database.models import (
    Base,
    Restaurant,
    Persona,
    Phrase,
    MessageLog,
    Config,
    AutomationRun,
    FollowStatus,
    InboxMessage,
)

from database.crud import get_db
from schemas.restaurant import RestaurantOut, RestaurantCreate, RestaurantUpdate
from schemas.persona import PersonaOut, PersonaCreate, PersonaUpdate
from schemas.phrase import (
    GlobalPhraseCreate,
    GlobalPhraseUpdate,
    GlobalPhraseOut,
)

from database.database import engine

Base.metadata.create_all(bind=engine)

app = FastAPI(
    title="Database API - Instagram Automation",
    description="API isolada responsável apenas pelo banco SQLite",
    version="1.0.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ======================
# ESTADO EM MEMÓRIA PARA WEBSOCKET
# ======================

active_websockets: list[WebSocket] = []
dm_stats = {"total": 0, "success": 0, "fail": 0}
recent_events: deque[dict] = deque(maxlen=50)


async def _broadcast_event(event: dict):
    """Envia um evento JSON para todos os websockets conectados.

    Remove conexões quebradas ao detectar erros de envio.
    """
    # Log de envio para facilitar o debug (aparecerá no stdout do uvicorn)
    try:
        print(f"[WS BROADCAST] -> sending event type={event.get('type')} to {len(active_websockets)} sockets")
    except Exception:
        pass

    dead: list[WebSocket] = []
    for ws in list(active_websockets):
        try:
            await ws.send_json(event)
        except Exception:
            # Log falha de envio e marca conexão como morta
            try:
                print("[WS BROADCAST] -> failed to send to a socket, removing")
            except Exception:
                pass
            dead.append(ws)
    for ws in dead:
        if ws in active_websockets:
            active_websockets.remove(ws)


@app.websocket("/automation/ws")
async def automation_ws(websocket: WebSocket):
    await websocket.accept()
    active_websockets.append(websocket)

    # Envia estado inicial de contadores
    await websocket.send_json({"type": "stats", "stats": dm_stats})

    # Envia histórico recente de eventos (até 50)
    if recent_events:
        await websocket.send_json({"type": "history", "items": list(recent_events)})

    try:
        while True:
            # Mantém conexão viva; ignoramos mensagens do cliente por enquanto
            await websocket.receive_text()
    except WebSocketDisconnect:
        if websocket in active_websockets:
            active_websockets.remove(websocket)


@app.post("/automation/logline")
async def automation_logline(payload: dict):
    """Recebe uma linha de log do backend principal e envia para todos os WebSockets como system_log.

    Não persiste em banco; é apenas para observabilidade em tempo real no frontend.
    """
    message = payload.get("message")
    level = payload.get("level", "INFO")
    logger_name = payload.get("logger")
    created_at = payload.get("created_at")

    event = {
        "type": "system_log",
        "level": level,
        "logger": logger_name,
        "message": message,
        "created_at": created_at,
        "stats": dm_stats,
    }

    # adiciona ao buffer de eventos recentes
    recent_events.append(event)

    if active_websockets:
        asyncio.create_task(_broadcast_event(event))

    return {"status": "ok"}


@app.post("/automation/emit")
async def automation_emit(payload: dict):
    """Recebe um evento pronto (ex: `dm_log`) e envia para todos os WebSockets.
    
    Atualiza as estatísticas globais antes de enviar.
    """
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="Payload must be a JSON object")

    event = payload
    
    # Atualiza estatísticas globais se for um evento dm_log
    if event.get("type") == "dm_log":
        dm_stats["total"] += 1
        if event.get("success"):
            dm_stats["success"] += 1
        else:
            dm_stats["fail"] += 1
    
    # Sempre inclui as estatísticas mais recentes no evento
    event["stats"] = dict(dm_stats)  # Envia uma cópia para evitar referências

    # Adiciona ao buffer de eventos recentes
    recent_events.append(event)

    # Envia para todos os clientes conectados
    if active_websockets:
        asyncio.create_task(_broadcast_event(event))

    return {"status": "emitted", "stats": dm_stats}


# ======================
# ROTAS - RESTAURANTES
# ======================
@app.get("/restaurants/", response_model=List[RestaurantOut])
def list_restaurants(skip: int = 0, limit: int = 1000, db: Session = Depends(get_db)):
    return db.query(Restaurant).offset(skip).limit(limit).all()


@app.get("/restaurants/{restaurant_id}", response_model=RestaurantOut)
def get_restaurant(restaurant_id: int, db: Session = Depends(get_db)):
    restaurant = db.query(Restaurant).filter(Restaurant.id == restaurant_id).first()
    if not restaurant:
        raise HTTPException(status_code=404, detail="Restaurante não encontrado")
    return restaurant


@app.post("/restaurants/", response_model=RestaurantOut, status_code=201)
def create_restaurant(restaurant_in: RestaurantCreate, db: Session = Depends(get_db)):
    existing = db.query(Restaurant).filter(Restaurant.instagram_username == restaurant_in.instagram_username).first()
    if existing:
        raise HTTPException(status_code=400, detail="Já existe um restaurante com esse instagram_username")

    db_restaurant = Restaurant(
        instagram_username=restaurant_in.instagram_username,
        name=restaurant_in.name,
        bloco=restaurant_in.bloco,
        cliente=restaurant_in.cliente,
    )
    db.add(db_restaurant)
    db.commit()
    db.refresh(db_restaurant)
    return db_restaurant


@app.post("/restaurants/bulk", status_code=201)
def bulk_create_restaurants(restaurants_in: List[RestaurantCreate], db: Session = Depends(get_db)):
    """Cria múltiplos restaurantes em uma única transação usando bulk insert.
    
    Usa inserção em lote para melhor performance e evita duplicatas baseado em instagram_username.
    """
    if not restaurants_in:
        return {"created": 0, "skipped": 0, "created_items": []}
    
    # Busca todos os usernames existentes de uma vez
    usernames_to_check = [r.instagram_username for r in restaurants_in]
    existing_restaurants = db.query(Restaurant).filter(
        Restaurant.instagram_username.in_(usernames_to_check)
    ).all()
    existing_usernames = {r.instagram_username for r in existing_restaurants}
    
    # Filtra apenas os restaurantes que não existem
    restaurants_to_create = []
    skipped_count = 0
    
    for r in restaurants_in:
        if r.instagram_username in existing_usernames:
            skipped_count += 1
            continue
        restaurants_to_create.append(
            Restaurant(
                instagram_username=r.instagram_username,
                name=r.name,
                bloco=r.bloco,
                cliente=r.cliente,
            )
        )
        existing_usernames.add(r.instagram_username)  # Evita duplicatas dentro do próprio batch
    
    if not restaurants_to_create:
        return {"created": 0, "skipped": skipped_count, "created_items": []}
    
    # Insere todos em uma única operação de bulk insert
    db.bulk_save_objects(restaurants_to_create)
    db.commit()
    
    # Busca os IDs dos restaurantes criados
    created_usernames = [r.instagram_username for r in restaurants_to_create]
    created_restaurants = db.query(Restaurant).filter(
        Restaurant.instagram_username.in_(created_usernames)
    ).all()
    
    return {
        "created": len(created_restaurants),
        "skipped": skipped_count,
        "created_items": [
            {
                "id": r.id,
                "instagram_username": r.instagram_username,
                "name": r.name,
                "bloco": r.bloco,
                "cliente": r.cliente,
            }
            for r in created_restaurants
        ]
    }


@app.put("/restaurants/{restaurant_id}", response_model=RestaurantOut)
def update_restaurant(restaurant_id: int, restaurant_in: RestaurantUpdate, db: Session = Depends(get_db)):
    restaurant = db.query(Restaurant).filter(Restaurant.id == restaurant_id).first()
    if not restaurant:
        raise HTTPException(status_code=404, detail="Restaurante não encontrado")

    if restaurant_in.instagram_username is not None:
        existing = (
            db.query(Restaurant)
            .filter(Restaurant.instagram_username == restaurant_in.instagram_username, Restaurant.id != restaurant_id)
            .first()
        )
        if existing:
            raise HTTPException(status_code=400, detail="Já existe outro restaurante com esse instagram_username")
        restaurant.instagram_username = restaurant_in.instagram_username

    if restaurant_in.name is not None:
        restaurant.name = restaurant_in.name
    if restaurant_in.bloco is not None:
        restaurant.bloco = int(restaurant_in.bloco)
    restaurant.cliente = restaurant_in.cliente

    db.commit()
    db.refresh(restaurant)
    return restaurant


@app.delete("/restaurants/{restaurant_id}", status_code=204)
def delete_restaurant(restaurant_id: int, db: Session = Depends(get_db)):
    restaurant = db.query(Restaurant).filter(Restaurant.id == restaurant_id).first()
    if not restaurant:
        raise HTTPException(status_code=404, detail="Restaurante não encontrado")

    # Deleta registros relacionados em MessageLog
    db.query(MessageLog).filter(MessageLog.restaurant_id == restaurant_id).delete()
    
    # Deleta registros relacionados em FollowStatus
    db.query(FollowStatus).filter(FollowStatus.restaurant_id == restaurant_id).delete()

    db.delete(restaurant)
    db.commit()
    return {"status": "deleted"}


@app.delete("/restaurants/", response_model=dict)
def delete_all_restaurants(db: Session = Depends(get_db)):
    """
    Deleta TODOS os restaurantes.
    Também remove registros relacionados (MessageLog e FollowStatus) para evitar erro de FK.
    """
    deleted_restaurants = db.query(Restaurant).count()

    # Limpa relacionamentos
    db.query(MessageLog).delete(synchronize_session=False)
    db.query(FollowStatus).delete(synchronize_session=False)

    # Deleta restaurantes
    db.query(Restaurant).delete(synchronize_session=False)
    db.commit()

    return {"deleted": deleted_restaurants}


# ======================
# ROTAS - PERSONAS
# ======================
@app.get("/personas/", response_model=List[PersonaOut])
def list_personas(db: Session = Depends(get_db)):
    return db.query(Persona).all()


@app.post("/personas/", response_model=PersonaOut)
def create_persona(persona: PersonaCreate, db: Session = Depends(get_db)):
    # Verifica se já existe uma persona com esse nome ou username
    existing = db.query(Persona).filter(
        (Persona.name == persona.name) |
        (Persona.instagram_username == persona.instagram_username)
    ).first()
    if existing:
        raise HTTPException(status_code=400, detail="Persona com este nome ou username já existe")

    db_persona = Persona(
        name=persona.name,
        instagram_username=persona.instagram_username,
        instagram_password=persona.instagram_password
    )
    db.add(db_persona)
    db.commit()
    db.refresh(db_persona)
    return db_persona


@app.post("/personas/bulk", status_code=201)
def bulk_create_personas(personas_in: List[PersonaCreate], db: Session = Depends(get_db)):
    """Cria múltiplas personas em uma única transação usando bulk insert.
    
    Usa inserção em lote para melhor performance e evita duplicatas baseado em name ou instagram_username.
    """
    if not personas_in:
        return {"created": 0, "skipped": 0, "created_items": []}
    
    # Busca todos os nomes e usernames existentes de uma vez
    names_to_check = [p.name for p in personas_in]
    usernames_to_check = [p.instagram_username for p in personas_in]
    
    existing_personas = db.query(Persona).filter(
        (Persona.name.in_(names_to_check)) |
        (Persona.instagram_username.in_(usernames_to_check))
    ).all()
    
    existing_names = {p.name for p in existing_personas}
    existing_usernames = {p.instagram_username for p in existing_personas}
    
    # Filtra apenas as personas que não existem
    personas_to_create = []
    skipped_count = 0
    
    for p in personas_in:
        if p.name in existing_names or p.instagram_username in existing_usernames:
            skipped_count += 1
            continue
        personas_to_create.append(
            Persona(
                name=p.name,
                instagram_username=p.instagram_username,
                instagram_password=p.instagram_password,
            )
        )
        existing_names.add(p.name)
        existing_usernames.add(p.instagram_username)  # Evita duplicatas dentro do próprio batch
    
    if not personas_to_create:
        return {"created": 0, "skipped": skipped_count, "created_items": []}
    
    # Insere todos em uma única operação de bulk insert
    db.bulk_save_objects(personas_to_create)
    db.commit()
    
    # Busca os IDs das personas criadas
    created_usernames = [p.instagram_username for p in personas_to_create]
    created_personas = db.query(Persona).filter(
        Persona.instagram_username.in_(created_usernames)
    ).all()
    
    return {
        "created": len(created_personas),
        "skipped": skipped_count,
        "created_items": [
            {
                "id": p.id,
                "name": p.name,
                "instagram_username": p.instagram_username,
            }
            for p in created_personas
        ]
    }


@app.get("/personas/{persona_id}", response_model=PersonaOut)
def get_persona(persona_id: int, db: Session = Depends(get_db)):
    persona = db.query(Persona).filter(Persona.id == persona_id).first()
    if not persona:
        raise HTTPException(status_code=404, detail="Persona não encontrada")
    return persona


@app.put("/personas/{persona_id}", response_model=PersonaOut)
def update_persona(persona_id: int, persona_in: PersonaUpdate, db: Session = Depends(get_db)):
    persona = db.query(Persona).filter(Persona.id == persona_id).first()
    if not persona:
        raise HTTPException(status_code=404, detail="Persona não encontrada")

    if persona_in.name is not None:
        existing_by_name = (
            db.query(Persona)
            .filter(Persona.name == persona_in.name, Persona.id != persona_id)
            .first()
        )
        if existing_by_name:
            raise HTTPException(status_code=400, detail="Já existe outra persona com esse nome")
        persona.name = persona_in.name

    if persona_in.instagram_username is not None:
        existing_by_username = (
            db.query(Persona)
            .filter(Persona.instagram_username == persona_in.instagram_username, Persona.id != persona_id)
            .first()
        )
        if existing_by_username:
            raise HTTPException(status_code=400, detail="Já existe outra persona com esse username")
        persona.instagram_username = persona_in.instagram_username

    if persona_in.instagram_password is not None:
        persona.instagram_password = persona_in.instagram_password

    db.commit()
    db.refresh(persona)
    return persona


@app.delete("/personas/{persona_id}", status_code=204)
def delete_persona(persona_id: int, db: Session = Depends(get_db)):
    persona = db.query(Persona).filter(Persona.id == persona_id).first()
    if not persona:
        raise HTTPException(status_code=404, detail="Persona não encontrada")

    # Deleta registros relacionados em MessageLog
    db.query(MessageLog).filter(MessageLog.persona_id == persona_id).delete()
    
    # Deleta registros relacionados em FollowStatus
    db.query(FollowStatus).filter(FollowStatus.persona_id == persona_id).delete()

    db.delete(persona)
    db.commit()
    return {"status": "deleted"}


@app.delete("/personas/", response_model=dict)
def delete_all_personas(db: Session = Depends(get_db)):
    """
    Deleta TODAS as personas.
    Também remove registros relacionados (MessageLog, FollowStatus, InboxMessage) para evitar erro de FK.
    """
    deleted_personas = db.query(Persona).count()

    db.query(MessageLog).delete(synchronize_session=False)
    db.query(FollowStatus).delete(synchronize_session=False)
    db.query(InboxMessage).delete(synchronize_session=False)

    db.query(Persona).delete(synchronize_session=False)
    db.commit()

    return {"deleted": deleted_personas}


# ======================
# ROTAS - FRASES (GLOBAIS / INDEPENDENTES)
# ======================


# ======================
# ROTAS - FRASES (GLOBAIS)
# ======================
@app.get("/phrases/", response_model=List[GlobalPhraseOut])
def list_phrases(db: Session = Depends(get_db)):
    """Lista todas as frases; frases são entidades independentes (não estão atreladas a personas)."""
    phrases = db.query(Phrase).order_by(Phrase.order).all()
    return phrases


@app.get("/phrases/{phrase_id}", response_model=GlobalPhraseOut)
def get_global_phrase(phrase_id: int, db: Session = Depends(get_db)):
    phrase = db.query(Phrase).filter(Phrase.id == phrase_id).first()
    if not phrase:
        raise HTTPException(status_code=404, detail="Frase não encontrada")
    return phrase


@app.post("/phrases/", response_model=GlobalPhraseOut, status_code=201)
def create_global_phrase(phrase_in: GlobalPhraseCreate, db: Session = Depends(get_db)):
    """Cria uma frase independente (não vinculada à persona)."""
    db_phrase = Phrase(
        text=phrase_in.text,
        order=phrase_in.order,
        cliente=phrase_in.cliente,
    )
    db.add(db_phrase)
    db.commit()
    db.refresh(db_phrase)
    return db_phrase


@app.post("/phrases/bulk", status_code=201)
def bulk_create_phrases(phrases_in: List[GlobalPhraseCreate], db: Session = Depends(get_db)):
    """Cria múltiplas frases em uma única transação usando bulk insert.
    
    Usa inserção em lote para melhor performance.
    Frases são consideradas duplicadas se tiverem o mesmo texto e ordem.
    """
    if not phrases_in:
        return {"created": 0, "skipped": 0, "created_items": []}
    
    # Busca frases existentes com mesmo texto e ordem
    # Busca todas as frases para verificar duplicatas (texto + ordem)
    # Em volumes grandes, isso pode ser otimizado futuramente, mas para a maioria dos casos funciona bem
    existing_keys = set()
    texts_to_check = [p.text.strip().lower() for p in phrases_in]
    
    # Busca apenas frases que podem ser duplicatas (mesmo texto ou mesma ordem)
    existing_phrases = db.query(Phrase).filter(
        (Phrase.text.in_([t for t in set(texts_to_check)]))
    ).all()
    
    for existing in existing_phrases:
        existing_keys.add((existing.text.strip().lower(), existing.order))
    
    # Filtra apenas as frases que não existem
    phrases_to_create = []
    skipped_count = 0
    
    for p in phrases_in:
        key = (p.text.strip().lower(), p.order)
        if key in existing_keys:
            skipped_count += 1
            continue
        phrases_to_create.append(
            Phrase(
                text=p.text,
                order=p.order,
                cliente=p.cliente,
            )
        )
        existing_keys.add(key)  # Evita duplicatas dentro do próprio batch
    
    if not phrases_to_create:
        return {"created": 0, "skipped": skipped_count, "created_items": []}
    
    # Insere todos em uma única operação de bulk insert
    db.bulk_save_objects(phrases_to_create)
    db.commit()
    
    # Busca os IDs das frases criadas
    created_phrases = db.query(Phrase).filter(
        Phrase.text.in_([p.text for p in phrases_to_create])
    ).all()
    
    # Ordena para corresponder à ordem de inserção (aproximadamente)
    created_by_text_order = {(p.text.strip().lower(), p.order): p for p in created_phrases}
    result_items = []
    for p in phrases_to_create:
        key = (p.text.strip().lower(), p.order)
        if key in created_by_text_order:
            phrase = created_by_text_order[key]
            result_items.append({
                "id": phrase.id,
                "text": phrase.text,
                "order": phrase.order,
                "cliente": phrase.cliente,
            })
    
    return {
        "created": len(result_items),
        "skipped": skipped_count,
        "created_items": result_items
    }


@app.put("/phrases/{phrase_id}", response_model=GlobalPhraseOut)
def update_global_phrase(phrase_id: int, phrase_in: GlobalPhraseUpdate, db: Session = Depends(get_db)):
    phrase = db.query(Phrase).filter(Phrase.id == phrase_id).first()
    if not phrase:
        raise HTTPException(status_code=404, detail="Frase não encontrada")

    if phrase_in.text is not None:
        phrase.text = phrase_in.text
    if phrase_in.order is not None:
        phrase.order = phrase_in.order
    phrase.cliente = phrase_in.cliente

    db.commit()
    db.refresh(phrase)
    return phrase


@app.delete("/phrases/{phrase_id}", status_code=204)
def delete_global_phrase(phrase_id: int, db: Session = Depends(get_db)):
    phrase = db.query(Phrase).filter(Phrase.id == phrase_id).first()
    if not phrase:
        raise HTTPException(status_code=404, detail="Frase não encontrada")

    db.delete(phrase)
    db.commit()
    return {"status": "deleted"}


@app.delete("/phrases/", response_model=dict)
def delete_all_phrases(db: Session = Depends(get_db)):
    """
    Deleta TODAS as frases.
    Remove MessageLog antes para evitar FK (MessageLog.phrase_id).
    """
    deleted_phrases = db.query(Phrase).count()

    db.query(MessageLog).delete(synchronize_session=False)
    db.query(Phrase).delete(synchronize_session=False)
    db.commit()

    return {"deleted": deleted_phrases}


# ======================
# LOG DE MENSAGENS
# ======================
@app.post("/log/")
async def log_sent_message(payload: dict, db: Session = Depends(get_db)):
    restaurant_id = payload.get("restaurant_id")
    persona_id = payload.get("persona_id")
    phrase_id = payload.get("phrase_id")
    success = bool(payload.get("success", True))
    automation_run_id = payload.get("automation_run_id")

    if not all([restaurant_id, persona_id, phrase_id]):
        raise HTTPException(status_code=400, detail="restaurant_id, persona_id e phrase_id são obrigatórios")

    log = MessageLog(
        restaurant_id=restaurant_id,
        persona_id=persona_id,
        phrase_id=phrase_id,
        success=success,
        automation_run_id=automation_run_id,
    )
    db.add(log)
    db.commit()
    db.refresh(log)

    # Atualiza contadores agregados em memória
    dm_stats["total"] += 1
    if success:
        dm_stats["success"] += 1
    else:
        dm_stats["fail"] += 1

    # Carrega informações relacionadas para enviar ao frontend
    restaurant = db.query(Restaurant).filter(Restaurant.id == restaurant_id).first()
    persona = db.query(Persona).filter(Persona.id == persona_id).first()
    phrase = db.query(Phrase).filter(Phrase.id == phrase_id).first()

    ts = log.sent_at.isoformat() if log.sent_at else None

    event = {
        "type": "dm_log",
        "id": log.id,
        "success": success,
        "sent_at": ts,
        "automation_run_id": automation_run_id,
        "stats": dm_stats,
        "restaurant": {
            "id": restaurant.id if restaurant else restaurant_id,
            "instagram_username": getattr(restaurant, "instagram_username", None),
            "name": getattr(restaurant, "name", None),
            "bloco": getattr(restaurant, "bloco", None),
        },
        "persona": {
            "id": persona.id if persona else persona_id,
            "instagram_username": getattr(persona, "instagram_username", None),
            "name": getattr(persona, "name", None),
        },
        "phrase": {
            "id": phrase.id if phrase else phrase_id,
            "text": getattr(phrase, "text", None),
        },
    }

    # Linha de log pré-formatada para o frontend (não inclui texto da frase)
    try:
        ts_display = ""
        if ts:
            from datetime import datetime

            ts_display = datetime.fromisoformat(ts).time().strftime("%H:%M:%S")
        status = "OK" if success else "FAIL"
        rest_username = getattr(restaurant, "instagram_username", None) if restaurant else None
        rest_name = getattr(restaurant, "name", None) if restaurant else None
        rest_bloco = getattr(restaurant, "bloco", None) if restaurant else None
        persona_username = getattr(persona, "instagram_username", None) if persona else None
        persona_name = getattr(persona, "name", None) if persona else None
        phrase_id_display = phrase.id if phrase else phrase_id

        line = (
            f"[{ts_display}] {status} "
            f"restaurante=@{rest_username or '?'} (id={restaurant.id if restaurant else restaurant_id}, bloco={rest_bloco if rest_bloco is not None else '-'}, nome={rest_name or '?'}) | "
            f"persona=@{persona_username or '?'} (id={persona.id if persona else persona_id}, nome={persona_name or '?'}) | "
            f"frase#{phrase_id_display or '?'}"
        )
        event["line"] = line
    except Exception:
        # Em caso de erro de formatação, simplesmente não inclui 'line'
        pass

    # adiciona ao buffer de eventos recentes
    recent_events.append(event)

    # Dispara envio assíncrono para todos os websockets
    if active_websockets:
        asyncio.create_task(_broadcast_event(event))

    return {"status": "logged", "id": log.id}


@app.post("/runs/", status_code=201)
def create_automation_run(db: Session = Depends(get_db)):
    run = AutomationRun()
    db.add(run)
    db.commit()
    db.refresh(run)
    return {"id": run.id, "started_at": run.started_at}


@app.post("/runs/{run_id}/finish")
def finish_automation_run(run_id: int, db: Session = Depends(get_db)):
    run = db.query(AutomationRun).filter(AutomationRun.id == run_id).first()
    if not run:
        raise HTTPException(status_code=404, detail="Run não encontrada")
    if run.finished_at is None:
        run.finished_at = func.now()
        db.commit()
        db.refresh(run)
    return {"id": run.id, "started_at": run.started_at, "finished_at": run.finished_at}


@app.get("/last-message/{restaurant_id}")
def get_last_message(restaurant_id: int, db: Session = Depends(get_db)):
    last = (
        db.query(MessageLog)
        .filter(MessageLog.restaurant_id == restaurant_id)
        .order_by(MessageLog.sent_at.desc())
        .first()
    )
    if not last:
        return None
    return {
        "persona_id": last.persona_id,
        "phrase_id": last.phrase_id,
        "sent_at": last.sent_at.isoformat() if last.sent_at else None
    }


@app.get("/follow-status/{restaurant_id}/{persona_id}")
def get_follow_status(restaurant_id: int, persona_id: int, db: Session = Depends(get_db)):
    status = (
        db.query(FollowStatus)
        .filter(FollowStatus.restaurant_id == restaurant_id, FollowStatus.persona_id == persona_id)
        .first()
    )
    if not status:
        return {
            "restaurant_id": restaurant_id,
            "persona_id": persona_id,
            "restaurant_follows_persona": False,
            "persona_follows_restaurant": False,
            "last_checked": None,
        }

    return {
        "restaurant_id": status.restaurant_id,
        "persona_id": status.persona_id,
        "restaurant_follows_persona": bool(status.restaurant_follows_persona),
        "persona_follows_restaurant": bool(status.persona_follows_restaurant),
        "last_checked": status.last_checked.isoformat() if status.last_checked else None,
    }


@app.post("/follow-status/")
def upsert_follow_status(payload: dict, db: Session = Depends(get_db)):
    restaurant_id = payload.get("restaurant_id")
    persona_id = payload.get("persona_id")
    if not restaurant_id or not persona_id:
        raise HTTPException(status_code=400, detail="restaurant_id e persona_id são obrigatórios")

    status = (
        db.query(FollowStatus)
        .filter(FollowStatus.restaurant_id == restaurant_id, FollowStatus.persona_id == persona_id)
        .first()
    )
    if not status:
        status = FollowStatus(restaurant_id=restaurant_id, persona_id=persona_id)
        db.add(status)

    if "restaurant_follows_persona" in payload:
        status.restaurant_follows_persona = bool(payload["restaurant_follows_persona"])
    if "persona_follows_restaurant" in payload:
        status.persona_follows_restaurant = bool(payload["persona_follows_restaurant"])

    from datetime import datetime

    status.last_checked = datetime.utcnow()
    db.commit()
    db.refresh(status)

    return {
        "restaurant_id": status.restaurant_id,
        "persona_id": status.persona_id,
        "restaurant_follows_persona": bool(status.restaurant_follows_persona),
        "persona_follows_restaurant": bool(status.persona_follows_restaurant),
        "last_checked": status.last_checked.isoformat() if status.last_checked else None,
    }


@app.get("/config/{key}")
def get_config(key: str, db: Session = Depends(get_db)):
    config = db.query(Config).filter(Config.key == key).first()
    if not config:
        raise HTTPException(404, f"Config '{key}' não encontrada")
    return {"key": config.key, "value": config.value, "description": config.description}


@app.get("/config/")
def list_configs(db: Session = Depends(get_db)):
    """Retorna todas as configs como um objeto chave -> {value, description}"""
    configs = db.query(Config).all()
    return {c.key: {"value": c.value, "description": c.description} for c in configs}


@app.post("/config/")
def config_action(payload: dict, db: Session = Depends(get_db)):
    """
    Unified config endpoint. Behavior based on payload:
    - Single fetch: { "key": "rest_days" } -> returns {key,value,description}
    - Single set: { "key": "rest_days", "value": "3", "description": "..." }
    - Bulk set: { "rest_days": "3", "foo": {"value":"bar","description":"x"} }
    """
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="Payload must be a JSON object")

    # Single fetch: only 'key' provided
    if "key" in payload and len(payload) == 1:
        key = payload["key"]
        config = db.query(Config).filter(Config.key == key).first()
        if not config:
            raise HTTPException(status_code=404, detail=f"Config '{key}' not found")
        return {"key": config.key, "value": config.value, "description": config.description}

    # Single set: contains 'key' and 'value'
    if "key" in payload and "value" in payload:
        key = payload["key"]
        value = str(payload.get("value") or "")
        description = str(payload.get("description") or "")
        config = db.query(Config).filter(Config.key == key).first()
        if config:
            config.value = value
            config.description = description
            action = "updated"
        else:
            config = Config(key=key, value=value, description=description)
            db.add(config)
            action = "created"
        db.commit()
        return {"status": "ok", "key": key, "value": value, "action": action}

    # Otherwise treat as bulk: each top-level key is a config key
    results = []
    for key, entry in payload.items():
        if key == "_":
            continue
        if isinstance(entry, dict):
            value = entry.get("value")
            description = entry.get("description", "")
        else:
            value = entry
            description = ""
        value = str(value) if value is not None else ""

        config = db.query(Config).filter(Config.key == key).first()
        if config:
            config.value = value
            config.description = description
            action = "updated"
        else:
            config = Config(key=key, value=value, description=description)
            db.add(config)
            action = "created"
        results.append({"key": key, "value": value, "description": description, "action": action})

    db.commit()
    return {"status": "ok", "results": results}

# ======================
# RELATÓRIOS XLSX
# ======================
@app.get("/reports/messages.xlsx")
def messages_report(
    period: str = "all",  # "week", "month", "all"
    persona_id: Optional[int] = None,
    restaurant_id: Optional[int] = None,
    status: str = "all",  # "all", "success", "fail"
    db: Session = Depends(get_db),
):
    """Exporta histórico de mensagens em XLSX.

    period:
      - "week": últimos 7 dias
      - "month": desde o primeiro dia do mês atual
      - "all": todo o período

    status:
      - "all": todos
      - "success": apenas sucessos
      - "fail": apenas falhas
    """

    now = datetime.utcnow()
    start_dt: datetime | None = None

    p = (period or "").lower()
    if p == "week":
        start_dt = now - timedelta(days=7)
    elif p == "month":
        start_dt = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    else:
        start_dt = None  # all

    q = (
        db.query(MessageLog, Restaurant, Persona, Phrase)
        .join(Restaurant, MessageLog.restaurant_id == Restaurant.id)
        .join(Persona, MessageLog.persona_id == Persona.id)
        .join(Phrase, MessageLog.phrase_id == Phrase.id)
    )

    if start_dt is not None:
        q = q.filter(MessageLog.sent_at >= start_dt)
    if persona_id is not None:
        q = q.filter(MessageLog.persona_id == persona_id)
    if restaurant_id is not None:
        q = q.filter(MessageLog.restaurant_id == restaurant_id)

    s = (status or "").lower()
    if s == "success":
        q = q.filter(MessageLog.success.is_(True))
    elif s == "fail":
        q = q.filter(MessageLog.success.is_(False))

    q = q.order_by(MessageLog.sent_at.asc())

    # Cria planilha XLSX em memória
    wb = Workbook()
    ws = wb.active
    ws.title = "Mensagens"

    # Cabeçalho com nomes mais intuitivos e apenas campos cruciais
    ws.append(
        [
            "Data envio",
            "Status",
            "Restaurante (username)",
            "Restaurante (nome)",
            "Bloco",
            "Persona (username)",
            "Persona (nome)",
            "Frase ID",
            "Texto da frase",
        ]
    )

    for log, restaurant, persona, phrase in q.all():
        status_label = "Sucesso" if log.success else "Falha"
        sent_at_str = log.sent_at.isoformat() if log.sent_at else ""
        ws.append(
            [
                sent_at_str,
                status_label,
                getattr(restaurant, "instagram_username", "") if restaurant else "",
                getattr(restaurant, "name", "") if restaurant else "",
                getattr(restaurant, "bloco", "") if restaurant else "",
                getattr(persona, "instagram_username", "") if persona else "",
                getattr(persona, "name", "") if persona else "",
                phrase.id if phrase else log.phrase_id,
                getattr(phrase, "text", "") if phrase else "",
            ]
        )

    output = io.BytesIO()
    wb.save(output)
    xlsx_data = output.getvalue()
    return Response(
        content=xlsx_data,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": "attachment; filename=messages_report.xlsx"},
    )


# ======================
# INBOX MESSAGES (Mensagens Recebidas)
# ======================
@app.post("/inbox-messages/", status_code=201)
def create_inbox_message(payload: dict, db: Session = Depends(get_db)):
    """Cria ou atualiza uma mensagem recebida do inbox."""
    persona_id = payload.get("persona_id")
    thread_id = payload.get("thread_id")
    item_id = payload.get("item_id")
    sender_user_id = payload.get("sender_user_id")
    sender_username = payload.get("sender_username")
    message_text = payload.get("message_text", "")
    received_at = payload.get("received_at")
    email_sent = payload.get("email_sent", False)
    
    if not all([persona_id, thread_id, item_id, sender_user_id, sender_username]):
        raise HTTPException(
            status_code=400,
            detail="persona_id, thread_id, item_id, sender_user_id e sender_username são obrigatórios"
        )
    
    # Verifica se já existe
    existing = db.query(InboxMessage).filter(InboxMessage.item_id == item_id).first()
    if existing:
        # Atualiza se necessário
        if received_at:
            from datetime import datetime
            if isinstance(received_at, str):
                received_at = datetime.fromisoformat(received_at.replace('Z', '+00:00'))
            existing.received_at = received_at
        existing.email_sent = email_sent
        db.commit()
        db.refresh(existing)
        return {
            "id": existing.id,
            "persona_id": existing.persona_id,
            "item_id": existing.item_id,
            "created": False
        }
    
    # Cria nova mensagem
    inbox_msg = InboxMessage(
        persona_id=persona_id,
        thread_id=thread_id,
        item_id=item_id,
        sender_user_id=sender_user_id,
        sender_username=sender_username,
        message_text=message_text,
        email_sent=email_sent,
    )
    
    if received_at:
        from datetime import datetime
        if isinstance(received_at, str):
            received_at = datetime.fromisoformat(received_at.replace('Z', '+00:00'))
        inbox_msg.received_at = received_at
    
    db.add(inbox_msg)
    db.commit()
    db.refresh(inbox_msg)
    
    return {
        "id": inbox_msg.id,
        "persona_id": inbox_msg.persona_id,
        "item_id": inbox_msg.item_id,
        "created": True
    }


@app.get("/inbox-messages/")
def list_inbox_messages(
    persona_id: Optional[int] = None,
    skip: int = 0,
    limit: int = 100,
    db: Session = Depends(get_db)
):
    """Lista mensagens recebidas do inbox."""
    query = db.query(InboxMessage)
    
    if persona_id:
        query = query.filter(InboxMessage.persona_id == persona_id)
    
    messages = query.order_by(InboxMessage.received_at.desc()).offset(skip).limit(limit).all()
    
    return [
        {
            "id": msg.id,
            "persona_id": msg.persona_id,
            "thread_id": msg.thread_id,
            "item_id": msg.item_id,
            "sender_user_id": msg.sender_user_id,
            "sender_username": msg.sender_username,
            "message_text": msg.message_text,
            "received_at": msg.received_at.isoformat() if msg.received_at else None,
            "email_sent": msg.email_sent,
        }
        for msg in messages
    ]


@app.get("/inbox-messages/check/{item_id}")
def check_inbox_message_exists(item_id: str, db: Session = Depends(get_db)):
    """Verifica se uma mensagem já existe pelo item_id."""
    message = db.query(InboxMessage).filter(InboxMessage.item_id == item_id).first()
    return {"exists": message is not None, "item_id": item_id}


@app.get("/inbox-messages/persona/{persona_id}/last-checked")
def get_last_checked_item_ids(persona_id: int, db: Session = Depends(get_db)):
    """Retorna todos os item_ids já processados para uma persona (para evitar duplicatas)."""
    messages = db.query(InboxMessage.item_id).filter(InboxMessage.persona_id == persona_id).all()
    return {"persona_id": persona_id, "item_ids": [m[0] for m in messages]}


# ======================
# HEALTH CHECK
# ======================
@app.get("/")
def health():
    return {"status": "Database API rodando perfeitamente"}