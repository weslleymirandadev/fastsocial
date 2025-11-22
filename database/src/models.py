from pydantic import BaseModel
from typing import Optional

class EnvioCreate(BaseModel):
    restaurante_id: int
    persona_id: int
    frase_numero: int

class EnvioResponse(BaseModel):
    id: int
    restaurante: str
    instagram: str
    persona_nome: str
    frase_numero: int
    frase_texto: str
    bloco: int
    data_envio: str