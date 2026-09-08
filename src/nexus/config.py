"""Application configuration using pydantic-settings."""

from pathlib import Path

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

    # Temporal (ADR 0001). These were read straight from os.environ, which meant
    # a value in .env was silently ignored: pydantic-settings loads .env into
    # Settings without exporting it to the process environment. Declaring them
    # here makes .env work for local development while docker-compose's real
    # environment variables still win, since os.environ takes precedence over
    # .env for every Settings field.
    use_temporal: bool = False
    temporal_host: str = "localhost:7233"
    temporal_namespace: str = "default"

    # Obsidian vault (ADR 0002). Empty disables the integration entirely.
    # A company's vault is <obsidian_vault_root>/<company_id>/; tenant
    # isolation is the path root, not a per-read authorization check.
    obsidian_vault_root: str = ""
    # Read cap per note, enforced before the file is opened.
    obsidian_max_note_bytes: int = 1_048_576

    # Application
    app_name: str = "NEXUS"
    app_version: str = "0.1.0"

    model_config = {
        "env_prefix": "",
        # Anchored to the repository root rather than the process CWD. A bare
        # ".env" is resolved against wherever the server was started, so running
        # `uvicorn nexus.main:app` from src/ — which is what INSTALLATION.md
        # documents — silently loaded no .env at all, and every setting fell back
        # to the defaults below. That failure is invisible: the app starts, and
        # only a value that differs from its default reveals the problem.
        #
        # Real environment variables still take precedence, so docker-compose,
        # CI, and shell overrides are unaffected. A missing file is ignored.
        "env_file": str(Path(__file__).resolve().parents[2] / ".env"),
        "env_file_encoding": "utf-8",
        "case_sensitive": False,
        "extra": "ignore",
    }


settings = Settings()
