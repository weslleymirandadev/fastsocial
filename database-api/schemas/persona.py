from pydantic import BaseModel, Field, validator
from typing import Optional
import datetime


class PersonaBase(BaseModel):
    name: str = Field(
        ..., 
        min_length=1, 
        max_length=100, 
        description="Nome único da persona (ex: 'Maria_Sudeste', 'João_Norte')"
    )
    instagram_username: str = Field(..., description="Username do Instagram da persona")
    instagram_password: str = Field(..., description="Senha do Instagram da persona")



class PersonaCreate(PersonaBase):
    """
    Dados necessários para criar uma nova persona.
    Só salvamos username e password - o login será feito na hora da automação.
    """
    instagram_username: str = Field(..., description="Username do Instagram da persona")
    instagram_password: str = Field(..., description="Senha do Instagram da persona")

    @validator("instagram_username")
    def username_cannot_be_empty(cls, v):
        v = v.strip()
        if not v:
            raise ValueError("instagram_username não pode ser vazio")
        if v.startswith("@"):
            v = v[1:]
        return v

    @validator("instagram_password")
    def password_strength(cls, v):
        if len(v.strip()) < 6:
            raise ValueError("A senha deve ter pelo menos 6 caracteres")
        return v.strip()


class PersonaUpdate(BaseModel):
    """
    Atualização parcial da persona (qualquer campo pode ser alterado)
    """
    name: Optional[str] = Field(None, min_length=1, max_length=100)
    instagram_username: Optional[str] = None
    instagram_password: Optional[str] = None

    @validator("instagram_username", pre=True, always=True)
    def clean_username(cls, v):
        if v is None:
            return v
        v = v.strip()
        if v.startswith("@"):
            v = v[1:]
        return v if v else None


class PersonaOut(PersonaBase):
    id: int
    instagram_username: str = Field(..., description="Username do Instagram da persona")
    created_at: Optional[datetime.datetime] = None

    class Config:
        # Compatibilidade com SQLAlchemy / Pydantic v1/v2
        orm_mode = True
        try:
            from_attributes = True
        except Exception:
            pass