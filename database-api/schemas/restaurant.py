from pydantic import BaseModel, Field, validator
from typing import Optional
import datetime


class RestaurantBase(BaseModel):
    instagram_username: str = Field(
        ..., 
        min_length=1,
        max_length=100,
        description="Username do Instagram do restaurante (sem o @)"
    )
    date: Optional[datetime.date] = Field(
        None,
        description="Data em que foi realizado o cadastro do restaurante"
    )
    name: Optional[str] = Field(
        None, 
        max_length=200,
        description="Nome oficial do restaurante (ex: 'Cantina do Zé')"
    )
    bloco: Optional[int] = Field(
        None, 
        description="Bloco de restaurante"
    )
    ultima_persona: Optional[str] = Field(
        None, 
        description="Última persona usada"
    )
    ultima_frase_num: Optional[int] = Field(
        None, 
        description="Última frase usada"
    )
    ultima_frase_text: Optional[str] = Field(
        None, 
        description="Última frase usada"
    )


class RestaurantCreate(RestaurantBase):
    """
    Dados necessários para cadastrar um novo restaurante.
    """
    @validator("instagram_username")
    def clean_username(cls, v):
        username = v.strip().lower()
        if username.startswith("@"):
            username = username[1:]
        if not username:
            raise ValueError("instagram_username não pode ficar vazio")
        return username

    @validator("name", pre=True, always=True)
    def strip_optional_fields(cls, v):
        if v is None:
            return v
        return v.strip() or None


class RestaurantUpdate(BaseModel):
    """
    Atualização parcial de um restaurante existente.
    """
    instagram_username: Optional[str] = Field(None, max_length=100)
    name: Optional[str] = Field(None, max_length=200)
    city: Optional[str] = Field(None, max_length=100)

    @validator("instagram_username", pre=True, always=True)
    def clean_username_update(cls, v):
        if v is None:
            return v
        username = v.strip().lower()
        if username.startswith("@"):
            username = username[1:]
        return username or None


class RestaurantOut(RestaurantBase):
    """
    Resposta pública retornada nas rotas GET.
    """
    id: int
    created_at: Optional[str] = None

    class Config:
        from_attributes = True