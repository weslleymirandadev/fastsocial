from sqlalchemy import (
    Column,
    Integer,
    String,
    Text,
    Date,
    DateTime,
    ForeignKey,
    func,
    Boolean,
)
from sqlalchemy.orm import relationship
from sqlalchemy.ext.declarative import declarative_base

Base = declarative_base()


class Config(Base):
    __tablename__ = "config"

    key = Column(String(100), primary_key=True)
    value = Column(Text, nullable=False)
    description = Column(Text, nullable=True)


class Restaurant(Base):
    __tablename__ = "restaurants"

    id = Column(Integer, primary_key=True, index=True)
    instagram_username = Column(String(100), unique=True, nullable=False, index=True)
    date = Column(Date, nullable=True)
    name = Column(String(200), nullable=True)
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
    messages = relationship("MessageLog", back_populates="persona")


class Phrase(Base):
    __tablename__ = "phrases"

    id = Column(Integer, primary_key=True, index=True)
    text = Column(Text, nullable=False)
    order = Column(Integer, nullable=False)  # ordem dentro da persona (1, 2, 3...)

    # Relacionamentos
    # Phrase is now an independent entity (not tied to Persona)
    messages = relationship("MessageLog", back_populates="phrase")


class AutomationRun(Base):
    __tablename__ = "automation_runs"

    id = Column(Integer, primary_key=True, index=True)
    started_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)
    finished_at = Column(DateTime(timezone=True), nullable=True, index=True)


class MessageLog(Base):
    __tablename__ = "message_logs"

    id = Column(Integer, primary_key=True, index=True)
    restaurant_id = Column(Integer, ForeignKey("restaurants.id"), nullable=False)
    persona_id = Column(Integer, ForeignKey("personas.id"), nullable=False)
    phrase_id = Column(Integer, ForeignKey("phrases.id"), nullable=False)
    sent_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)
    success = Column(Boolean, nullable=False, default=True)
    automation_run_id = Column(Integer, ForeignKey("automation_runs.id"), nullable=True)

    restaurant = relationship("Restaurant", back_populates="messages")
    persona = relationship("Persona", back_populates="messages")
    phrase = relationship("Phrase", back_populates="messages")


class FollowStatus(Base):
    __tablename__ = "follow_status"

    id = Column(Integer, primary_key=True, index=True)
    restaurant_id = Column(Integer, ForeignKey("restaurants.id"), nullable=False, index=True)
    persona_id = Column(Integer, ForeignKey("personas.id"), nullable=False, index=True)
    restaurant_follows_persona = Column(Boolean, nullable=False, default=False)
    persona_follows_restaurant = Column(Boolean, nullable=False, default=False)
    last_checked = Column(DateTime(timezone=True), nullable=True)