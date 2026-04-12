from pydantic_settings import BaseSettings
from pydantic import ConfigDict
from functools import lru_cache


class Settings(BaseSettings):
    model_config = ConfigDict(
        env_file=".env",
        case_sensitive=False,
        extra="ignore",
    )

    # App
    app_name: str = "Chatbot API"
    debug: bool = False
    environment: str = "production"
    secret_key: str = "dev_secret_key_change_in_production"

    # Database
    database_url: str = "postgresql+asyncpg://chatbot:chatbot_secret@postgres:5432/chatbot_db"

    # Redis
    redis_url: str = "redis://redis:6379/0"

    # IA
    ai_provider: str = "anthropic"
    anthropic_api_key: str = ""
    openai_api_key: str = ""

    # n8n
    n8n_webhook_secret: str = "webhook_secret_change_me"
    n8n_callback_url: str = ""  # URL do n8n para receber eventos (ex: agente respondeu)

    # Session
    session_ttl_seconds: int = 1800
    human_handoff_urgency_threshold: float = 0.75
    conversation_timeout_minutes: int = 30  # Auto-fecha conversas inativas

    # Slack
    slack_webhook_url: str = ""
    slack_bot_token: str = ""
    slack_signing_secret: str = ""
    slack_handoff_channel: str = ""

    # Segurança
    api_key: str = ""  # Chave de API para endpoints administrativos
    rate_limit_per_minute: int = 60  # Requests por minuto por IP
    meta_app_secret: str = ""  # Meta App Secret para validar assinatura do Messenger

    # Uvicorn
    uvicorn_workers: int = 1

    # URL publica da API (usada em links do Slack)
    app_base_url: str = "http://localhost:8000"


@lru_cache
def get_settings() -> Settings:
    return Settings()
