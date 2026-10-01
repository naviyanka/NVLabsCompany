"""Application configuration using pydantic-settings."""

from pathlib import Path
from typing import Literal

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """NEXUS application settings.

    Values are loaded from environment variables with the NEXUS_ prefix,
    or from a .env file if present.
    """

    # Database
    database_url: str = "postgresql+asyncpg://nexus:nexus_dev_password@localhost:5432/nexus"
    system_database_url: str = ""
    allow_bypassrls_app_role: bool = False

    # Redis
    redis_url: str = "redis://localhost:6379/0"

    # Security
    secret_key: str = "dev-secret-key-change-in-production"

    # Local voice gateway (off unless an operator enables it and runs the worker).
    voice_enabled: bool = False
    voice_worker_url: str = "ws://127.0.0.1:8765"  # loopback only
    voice_worker_secret: str = ""  # shared with the worker; min 32 chars
    voice_ticket_ttl_seconds: int = 30
    voice_session_ttl_seconds: int = 1800
    voice_max_utterance_seconds: int = 30
    voice_idle_timeout_seconds: int = 60
    voice_utterances_per_minute: int = 12
    voice_sessions_per_minute: int = 10
    voice_company_utterances_per_minute: int = 60
    voice_company_sessions_per_minute: int = 30
    # Development only: allow in-process ticket/limit state when Redis is unreachable.
    voice_allow_local_state: bool = False
    voice_default_en: str = "en_US-ljspeech-medium"  # public domain; see docs/VOICE_GATEWAY.md
    voice_default_hi: str = (
        ""  # no commercially licensed Hindi voice ships; set to a user-supplied one
    )

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
    # The server runs in a container; the port mapping decides exposure.
    server_host: str = "0.0.0.0"  # nosec B104
    server_port: int = 8000
    # Where a CLI manager's MCP client reaches this API's manager bridge.
    # Empty: http://127.0.0.1:{server_port}/api/v1/mcp/manager.
    manager_bridge_url: str = ""

    # Data directory for JSON-persisted runtime state (control registry, etc.)
    data_dir: str = "./data"

    # Filesystem roots a workspace may be registered under, comma-separated.
    # "{company_id}" is substituted per tenant. Paths outside every root are
    # rejected, so a tenant cannot point a workspace at arbitrary host files.
    workspace_roots: str = "./data/workspaces/{company_id}"

    # Filesystem roots a repository's local clone may live under, same format
    # as workspace_roots. Git runs inside these directories, so a repository
    # whose local_path is outside every root is refused rather than used.
    repository_roots: str = "./data/repos/{company_id}"

    # Directory agent worktrees live under, one per company. "{company_id}" is
    # required, so one tenant's worktrees never share a root with another's.
    # Kept apart from repository_roots so a worktree can never be registered
    # as a repository. A worktree's stored relative_path is relative to this.
    worktree_root: str = "./data/worktrees/{company_id}"

    # Comma-separated secret-looking env var names every CLI employee may
    # inherit, on top of each backend's own allowlist, e.g. the key a custom
    # provider in ~/.codex/config.toml reads. Operator-only; never per request.
    cli_env_allowlist: str = ""

    # Secret vault backend: "fernet" (encrypted rows in the `secrets` table),
    # "keyring" (OS keychain, requires the `keyring` package), or "env"
    # (read-only, values come from NEXUS_SECRET_<REF> environment variables).
    secret_backend: str = "fernet"

    # Hermes native tool-calling provider (adapter_type "hermes_native"): an
    # OpenAI-compatible endpoint and the secret-backend ref of its API key. Operator-only,
    # never from agent config, so an agent cannot aim the key at another host.
    # Production gate for governed tool turns; off unless the operator enables it.
    hermes_native_tools_enabled: bool = False
    # Empty until configured: no endpoint, model or key is assumed.
    hermes_native_base_url: str = ""
    hermes_native_secret_ref: str = "hermes_native_api_key"
    # Default model ID, and the comma-separated IDs an agent's own model may select.
    hermes_native_model: str = ""
    hermes_native_models: str = ""

    # API Keys
    openai_api_key: str = ""
    anthropic_api_key: str = ""

    # LLM Connections / gateway (WP-22b..k). env_prefix is "", so the env var
    # name is the field name uppercased.
    # Comma-separated hostnames exempt from SSRF checks on connection create.
    llm_connection_host_allowlist: str = ""
    # R12 inversion switch: budget-infra failure fails closed unless True.
    budget_fail_open: bool = False
    # Gateway model-discovery cache TTL, seconds.
    gateway_catalog_refresh_seconds: int = 900
    # Opt-in company-wide halt on a Tier 1 quota-exhaustion webhook.
    gateway_kill_switch_on_quota: bool = False

    # Code sandbox (Phase 3.1): "local", "e2b", or "judge0".
    sandbox_backend: str = "local"
    # Local subprocess execution runs untrusted code with host privileges.
    # Must be opted into explicitly; every local run refuses while False.
    allow_unsafe_local_execution: bool = False
    e2b_api_key: str = ""
    judge0_base_url: str = "https://judge0-ce.p.rapidapi.com"
    judge0_api_key: str = ""

    # MCP/tool binding enforcement (ws05). "enforce" (the default since P3.2):
    # a call that fails a binding check, or has no agent identity, is denied.
    # "audit" lets it run and records it as would_deny; it is for rollout and
    # diagnosis only. RBAC, tool policy, autonomy and guardrail denials are
    # hard in both modes.
    tool_binding_enforcement: Literal["audit", "enforce"] = "enforce"

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

    # Governance & Concurrency (WP-19b, WP-18e, WP-20)
    tenant_bulkhead_per_tenant: int = 16
    budget_reconcile_enabled: bool = True
    rag_ranker: str = "rrf"

    # Durable employee chat turns (nexus.runtime.chat_turns)
    chat_turn_lease_seconds: int = 30  # renewed every third of this while a turn runs
    chat_turn_wait_seconds: float = 120.0  # POST waits this long, then answers 202
    chat_turn_max_attempts: int = 3  # executions before a turn with lost leases fails
    chat_turn_queue_ttl_seconds: int = 3600  # a turn queued this long expires
    chat_turn_poll_seconds: float = 1.0  # worker and waiter re-read the database this often

    # Durable employee task attempts (nexus.runtime.task_attempts)
    task_attempt_lease_seconds: int = 30  # claimed/verifying lease, renewed every third
    task_attempt_poll_seconds: float = 1.0  # attempt worker pass interval
    task_attempt_max_recoveries: int = 3  # lease losses before an attempt fails
    task_attempt_queue_ttl_seconds: int = 3600  # a queued attempt this old expires
    task_attempt_log_bytes: int = 64_000  # stdout/stderr kept per verification command
    # Bounded verification logs, one root per company like worktree_root. Stored
    # references are relative to this root, never absolute.
    task_attempt_evidence_root: str = "./data/task_evidence/{company_id}"

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
