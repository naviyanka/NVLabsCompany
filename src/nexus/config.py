"""Application configuration using pydantic-settings."""

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """NEXUS application settings.

    Values are loaded from environment variables with the NEXUS_ prefix,
    or from a .env file if present.
    """

    # Database
    database_url: str = "postgresql+asyncpg://nexus:nexus_dev_password@localhost:5432/nexus"

    # Redis
    redis_url: str = "redis://localhost:6379/0"

    # Security
    secret_key: str = "dev-secret-key-change-in-production"

    # Server
    debug: bool = False
    log_level: str = "INFO"
    server_host: str = "0.0.0.0"
    server_port: int = 8000

    # API Keys
    openai_api_key: str = ""
    anthropic_api_key: str = ""

    # Application
    app_name: str = "NEXUS"
    app_version: str = "0.1.0"

    model_config = {
        "env_prefix": "",
        "env_file": ".env",
        "env_file_encoding": "utf-8",
        "case_sensitive": False,
        "extra": "ignore",
    }


settings = Settings()
