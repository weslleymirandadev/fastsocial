from pydantic import BaseModel, Field, validator
from typing import Optional


class PhraseBase(BaseModel):
    text: str = Field(
        ..., 
        min_length=5,
        max_length=2000,
        description="Texto da mensagem que será enviada no Instagram (DM)"
    )


class PhraseCreate(PhraseBase):
    """
    Usado ao cadastrar uma nova frase para uma persona específica.
    """
    @validator("text")
    def strip_and_validate(cls, v):
        cleaned = v.strip().replace(";", "...")
        if not cleaned:
            raise ValueError("A frase não pode ser apenas espaços em branco")
        return cleaned


class PhraseUpdate(BaseModel):
    """
    Atualização parcial de uma frase já existente.
    """
    text: Optional[str] = Field(None, min_length=5, max_length=2000)
    order: Optional[int] = Field(None, ge=1)

    @validator("text", pre=True, always=True)
    def clean_text(cls, v):
        if v is None:
            return v
        cleaned = v.strip()
        if not cleaned:
            raise ValueError("A frase não pode ser apenas espaços em branco")
        return cleaned


class PhraseOut(PhraseBase):
    """
    Resposta pública que será retornada nas rotas GET.
    """
    id: int
    created_at: Optional[str] = None  # será retornado como ISO string

    class Config:
        from_attributes = True  # permite criar o modelo diretamente do objeto SQLAlchemy