from fastapi import FastAPI, HTTPException, Depends
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
from typing import List

from database.models import Base, Restaurant, Persona, Phrase, MessageLog
from database.crud import get_db
from schemas.restaurant import RestaurantOut, RestaurantCreate, RestaurantUpdate
from schemas.persona import PersonaOut, PersonaCreate, PersonaUpdate
from schemas.phrase import PhraseOut, PhraseCreate, PhraseUpdate

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
        city=restaurant_in.city,
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
    if restaurant_in.city is not None:
        restaurant.city = restaurant_in.city

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
    return None


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
    return None


# ======================
# ROTAS - FRASES
# ======================
@app.get("/personas/{persona_id}/phrases/", response_model=List[PhraseOut])
def list_phrases_by_persona(persona_id: int, db: Session = Depends(get_db)):
    phrases = db.query(Phrase).filter(Phrase.persona_id == persona_id).order_by(Phrase.order).all()
    if not phrases:
        raise HTTPException(status_code=404, detail="Esta persona não tem frases cadastradas")
    return phrases


@app.post("/personas/{persona_id}/phrases/", response_model=PhraseOut)
def create_phrase(persona_id: int, phrase: PhraseCreate, db: Session = Depends(get_db)):
    # Verifica se a persona existe
    persona = db.query(Persona).filter(Persona.id == persona_id).first()
    if not persona:
        raise HTTPException(status_code=404, detail="Persona não encontrada")

    db_phrase = Phrase(
        persona_id=persona_id,
        text=phrase.text,
        order=phrase.order
    )
    db.add(db_phrase)
    db.commit()
    db.refresh(db_phrase)
    return db_phrase


@app.get("/personas/{persona_id}/phrases/{phrase_id}", response_model=PhraseOut)
def get_phrase(persona_id: int, phrase_id: int, db: Session = Depends(get_db)):
    phrase = (
        db.query(Phrase)
        .filter(Phrase.id == phrase_id, Phrase.persona_id == persona_id)
        .first()
    )
    if not phrase:
        raise HTTPException(status_code=404, detail="Frase não encontrada para esta persona")
    return phrase


@app.put("/personas/{persona_id}/phrases/{phrase_id}", response_model=PhraseOut)
def update_phrase(persona_id: int, phrase_id: int, phrase_in: PhraseUpdate, db: Session = Depends(get_db)):
    phrase = (
        db.query(Phrase)
        .filter(Phrase.id == phrase_id, Phrase.persona_id == persona_id)
        .first()
    )
    if not phrase:
        raise HTTPException(status_code=404, detail="Frase não encontrada para esta persona")

    if phrase_in.text is not None:
        phrase.text = phrase_in.text
    if phrase_in.order is not None:
        phrase.order = phrase_in.order

    db.commit()
    db.refresh(phrase)
    return phrase


@app.delete("/personas/{persona_id}/phrases/{phrase_id}", status_code=204)
def delete_phrase(persona_id: int, phrase_id: int, db: Session = Depends(get_db)):
    phrase = (
        db.query(Phrase)
        .filter(Phrase.id == phrase_id, Phrase.persona_id == persona_id)
        .first()
    )
    if not phrase:
        raise HTTPException(status_code=404, detail="Frase não encontrada para esta persona")

    db.delete(phrase)
    db.commit()
    return None


# ======================
# LOG DE MENSAGENS
# ======================
@app.post("/log/")
def log_sent_message(restaurant_id: int, persona_id: int, phrase_id: int, db: Session = Depends(get_db)):
    log = MessageLog(
        restaurant_id=restaurant_id,
        persona_id=persona_id,
        phrase_id=phrase_id
    )
    db.add(log)
    db.commit()
    return {"status": "logged"}

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


# ======================
# HEALTH CHECK
# ======================
@app.get("/")
def health():
    return {"status": "Database API rodando perfeitamente"}