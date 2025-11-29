from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    DATABASE_API_URL: str = "http://localhost:8080"  # URL da database-api
    MAX_RETRIES: int = 3                             # Tentativas por mensagem falhada

    class Config:
        env_file = ".env"  # opcional: permite sobrescrever via .env


settings = Settings()