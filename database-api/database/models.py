# database-api/database/models.py
from sqlalchemy import (
    Column,
    Integer,
    String,
    Text,
    Date,
    DateTime,
    ForeignKey,
    func,
    UniqueConstraint,
)
from sqlalchemy.orm import relationship
from sqlalchemy.ext.declarative import declarative_base

Base = declarative_base()


class Restaurant(Base):
    __tablename__ = "restaurants"

    id = Column(Integer, primary_key=True, index=True)
    instagram_username = Column(String(100), unique=True, nullable=False, index=True)
    date = Column(Date, nullable=True)
    name = Column(String(200), nullable=True)
    city = Column(String(100), nullable=True)
    bloco = Column(Integer, nullable=True)
    ultima_persona = Column(String(200), nullable=True)
    ultima_frase_num = Column(Integer, nullable=True)
    ultima_frase_text = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    # Relacionamentos (opcional, mas útil)
    messages = relationship("MessageLog", back_populates="restaurant")


class Persona(Base):
    __tablename__ = "personas"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), unique=True, nullable=False)
    instagram_username = Column(String(100), unique=True, nullable=False)
    instagram_password = Column(String(255), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    # Relacionamentos
    phrases = relationship("Phrase", back_populates="persona", cascade="all, delete-orphan")
    messages = relationship("MessageLog", back_populates="persona")


class Phrase(Base):
    __tablename__ = "phrases"

    id = Column(Integer, primary_key=True, index=True)
    persona_id = Column(Integer, ForeignKey("personas.id"), nullable=False)
    text = Column(Text, nullable=False)
    order = Column(Integer, nullable=False)  # ordem dentro da persona (1, 2, 3...)

    # Garantir ordem única por persona
    __table_args__ = (
        UniqueConstraint("persona_id", "order", name="uix_persona_order"),
    )

    messages = relationship("MessageLog", back_populates="phrase")


class MessageLog(Base):
    __tablename__ = "message_logs"

    id = Column(Integer, primary_key=True, index=True)
    restaurant_id = Column(Integer, ForeignKey("restaurants.id"), nullable=False)
    persona_id = Column(Integer, ForeignKey("personas.id"), nullable=False)
    phrase_id = Column(Integer, ForeignKey("phrases.id"), nullable=False)
    sent_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)

    restaurant = relationship("Restaurant", back_populates="messages")
    persona = relationship("Persona", back_populates="messages")
    phrase = relationship("Phrase", back_populates="messages")