from sqlalchemy.orm import Session
from .database import SessionLocal

def get_db() -> Session:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def get_restaurant_by_username(db: Session, username: str):
    from .models import Restaurant
    return db.query(Restaurant).filter(Restaurant.instagram_username == username).first()


def get_persona_by_name(db: Session, name: str):
    from .models import Persona
    return db.query(Persona).filter(Persona.name == name).first()


def get_next_phrase_order(db: Session, persona_id: int) -> int:
    from .models import Phrase
    max_order = db.query(Phrase.order).filter(Phrase.persona_id == persona_id).order_by(Phrase.order.desc()).first()
    return (max_order[0] + 1) if max_order and max_order[0] is not None else 1