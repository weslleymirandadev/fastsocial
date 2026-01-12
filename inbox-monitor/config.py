from pydantic_settings import BaseSettings
from typing import List, Dict


class Settings(BaseSettings):
    # Database API configuration
    DATABASE_API_URL: str = "http://localhost:8080"  # URL da database-api
    
    # Email configuration
    SMTP_HOST: str = "smtp.gmail.com"
    SMTP_PORT: int = 587
    SMTP_USER: str = ""
    SMTP_PASSWORD: str = ""
    EMAIL_FROM: str = ""
    EMAIL_TO: str = ""
    
    # Monitor configuration
    CHECK_INTERVAL_SECONDS: int = 60  # Intervalo entre verificações
    MAX_RETRIES: int = 3
    
    class Config:
        env_file = ".env"


settings = Settings()

