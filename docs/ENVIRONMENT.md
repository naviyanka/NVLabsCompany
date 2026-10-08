# Environment Variables Reference

All configuration is done via environment variables. Copy `.env.example` → `.env` and fill in values.

## Backend (FastAPI)

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `DATABASE_URL` | Yes | `sqlite+aiosqlite:///./nexus.db` | Database connection URL (SQLite for dev, PostgreSQL for prod) |
| `NEXUS_ENV` | Yes for any deployment | — (unset) | Runtime environment: `production`, `staging`, `development` or `test`. Unset or unknown is treated as unsafe and cannot disable auth. |
| `AUTH_ENABLED` | No | `true` | Session-based auth. `false` is honoured only when `NEXUS_ENV=test`, or `NEXUS_ENV=development` with `NEXUS_ALLOW_INSECURE_AUTH_DISABLED=true`. In every other environment the server refuses to start. |
| `WEBHOOK_PROCESSING_TIMEOUT_SECONDS` | No | `120` | Hard limit on one inbound webhook's model run. Must be positive and, with a 60 s margin, below the 300 s idempotency lease (so under 240), or the server refuses to start. |
| `NEXUS_ALLOW_INSECURE_AUTH_DISABLED` | No | `false` | Development only. Acknowledges that `AUTH_ENABLED=false` trusts the `X-Company-Id` header, so any caller can act as any tenant. Ignored and refused in staging and production. |
| `CORS_ORIGINS` | No | `http://localhost:3000` | Comma-separated allowed origins |
| `ANTHROPIC_API_KEY` | No | — | Anthropic API key for Claude models |
| `OPENAI_API_KEY` | No | — | OpenAI API key for GPT models |
| `REDIS_URL` | No | — | Redis connection URL. Enables distributed rate limiting & leader election. |
| `COMPANY_RATE_LIMIT_PER_MINUTE` | No | `100` | API requests per minute for one company, shared by all of its users and open tabs; beyond it requests get 429. One dashboard page load makes about 20 requests and an idle tab about 25 a minute, so size it for the number of concurrent operators. |
| `EMBEDDING_PROVIDER` | No | `none` | Embedding provider: `openai`, `ollama`, or `none` |
| `OPENAI_EMBED_MODEL` | No | `text-embedding-3-small` | Embedding model when using OpenAI |
| `OLLAMA_EMBED_MODEL` | No | `nomic-embed-text` | Embedding model when using Ollama |
| `OLLAMA_EMBED_URL` | No | `http://localhost:11434` | Ollama API URL |
| `SECRET_BACKEND` | No | `fernet` | Secret vault store: `fernet` (encrypted rows in `secrets`), `keyring` (OS keychain), `env` (read-only `NEXUS_SECRET_<REF>` variables) |

## Frontend (Dashboard)

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `NEXUS_API_URL` | No | `http://localhost:8000` | Backend API URL for the proxy |
| `VITE_AUTH_ENABLED` | No | `true` | Mirror of backend AUTH_ENABLED for frontend |
| `PORT` | No | `3000` | Dashboard server port |

## Docker Compose

When using `docker-compose.yml`, the environment is pre-configured. Only set API keys:

```bash
# Create .env in project root
ANTHROPIC_API_KEY=sk-ant-...
OPENAI_API_KEY=sk-...
```

## Development Quick Start

```bash
# Backend
cd src && uvicorn nexus.main:app --port 8000 --reload

# Frontend (in another terminal)
cd dashboard && npx tsx server.ts
```
