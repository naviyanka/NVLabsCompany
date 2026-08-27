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

    # CORS
    cors_origins: str = "http://localhost:3000,http://localhost:5173"

    # Authentication
    # When False, requests without a resolvable principal fall back to the
    # legacy X-Company-Id header. Intended only as emergency escape hatch
    # during rollout; production must leave True.
    auth_enabled: bool = True
    session_cookie_name: str = "nv_session"
    csrf_cookie_name: str = "nv_csrf"
    # 7 days. Sessions are DB-backed, absolute expiry stored in the
    # user_sessions row as well as cookie max-age.
    session_lifetime_seconds: int = 604800
    # Set False only for plain-HTTP local development; browsers refuse to send
    # Secure cookies over http:// non-localhost origins.
    session_cookie_secure: bool = True
    session_cookie_samesite: str = "lax"
    # Minimum accepted password length for logins created through bootstrap,
    # setup, or invite acceptance.
    password_min_length: int = 12

    # SSO / OIDC
    oidc_enabled: bool = False
    oidc_issuer_url: str = ""
    oidc_client_id: str = ""
    oidc_client_secret: str = ""
    oidc_redirect_uri: str = ""
    oidc_scopes: str = "openid email profile"

    # Server
    debug: bool = False
    log_level: str = "INFO"
    server_host: str = "0.0.0.0"
    server_port: int = 8000

    # Data directory for JSON-persisted runtime state (control registry, etc.)
    data_dir: str = "./data"

    # Secret vault backend: "fernet" (encrypted rows in the `secrets` table),
    # "keyring" (OS keychain, requires the `keyring` package), or "env"
    # (read-only, values come from NEXUS_SECRET_<REF> environment variables).
    secret_backend: str = "fernet"

    # API Keys
    openai_api_key: str = ""
    anthropic_api_key: str = ""

    # Code sandbox (Phase 3.1): "local", "e2b", or "judge0".
    sandbox_backend: str = "local"
    # Local subprocess execution runs untrusted code with host privileges.
    # Must be opted into explicitly; every local run refuses while False.
    allow_unsafe_local_execution: bool = False
    e2b_api_key: str = ""
    judge0_base_url: str = "https://judge0-ce.p.rapidapi.com"
    judge0_api_key: str = ""

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
