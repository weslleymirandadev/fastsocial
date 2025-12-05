from pydantic import BaseModel, Field, validator
from typing import Optional
import datetime

class GlobalPhraseBase(BaseModel):
    text: str = Field(
        ..., 
        min_length=5,
        max_length=2000,
        description="Texto da mensagem que será enviada no Instagram (DM)",
    )
    # Phrase is independent from Persona now
    order: int = Field(..., ge=0, description="Ordem da frase (opcionalmente usada pela UI)")


class GlobalPhraseCreate(GlobalPhraseBase):
    @validator("text")
    def strip_and_validate(cls, v):
        cleaned = v.strip()
        if not cleaned:
            raise ValueError("A frase não pode ser apenas espaços em branco")
        return cleaned


class GlobalPhraseUpdate(BaseModel):
    text: Optional[str] = Field(None, min_length=5, max_length=2000)
    order: Optional[int] = Field(None, ge=0)
    # persona_id removed: phrases are independent

    @validator("text", pre=True, always=True)
    def clean_text(cls, v):
        if v is None:
            return v
        cleaned = v.strip()
        if not cleaned:
            raise ValueError("A frase não pode ser apenas espaços em branco")
        return cleaned


class GlobalPhraseOut(GlobalPhraseBase):
    id: int
    created_at: Optional[datetime.datetime] = None

    class Config:
        orm_mode = True
        try:
            from_attributes = True
        except Exception:
            pass