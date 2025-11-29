from fastapi import FastAPI, HTTPException, Depends, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
from typing import List
from sqlalchemy import func
import asyncio
from collections import deque

from database.models import Base, Restaurant, Persona, Phrase, MessageLog, Config, AutomationRun

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
    dead: list[WebSocket] = []
    for ws in list(active_websockets):
        try:
            await ws.send_json(event)
        except Exception:
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
    }

    # adiciona ao buffer de eventos recentes
    recent_events.append(event)

    if active_websockets:
        asyncio.create_task(_broadcast_event(event))

    return {"status": "ok"}


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
    )
    db.add(db_restaurant)
    db.commit()
    db.refresh(db_restaurant)
    return db_restaurant


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

    db.commit()
    db.refresh(restaurant)
    return restaurant


@app.delete("/restaurants/{restaurant_id}", status_code=204)
def delete_restaurant(restaurant_id: int, db: Session = Depends(get_db)):
    restaurant = db.query(Restaurant).filter(Restaurant.id == restaurant_id).first()
    if not restaurant:
        raise HTTPException(status_code=404, detail="Restaurante não encontrado")

    db.delete(restaurant)
    db.commit()
    return {"status": "deleted"}


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

    db.delete(persona)
    db.commit()
    return {"status": "deleted"}


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
    )
    db.add(db_phrase)
    db.commit()
    db.refresh(db_phrase)
    return db_phrase


@app.put("/phrases/{phrase_id}", response_model=GlobalPhraseOut)
def update_global_phrase(phrase_id: int, phrase_in: GlobalPhraseUpdate, db: Session = Depends(get_db)):
    phrase = db.query(Phrase).filter(Phrase.id == phrase_id).first()
    if not phrase:
        raise HTTPException(status_code=404, detail="Frase não encontrada")

    if phrase_in.text is not None:
        phrase.text = phrase_in.text
    if phrase_in.order is not None:
        phrase.order = phrase_in.order

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

    event = {
        "type": "dm_log",
        "id": log.id,
        "success": success,
        "sent_at": log.sent_at.isoformat() if log.sent_at else None,
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
# HEALTH CHECK
# ======================
@app.get("/")
def health():
    return {"status": "Database API rodando perfeitamente"}