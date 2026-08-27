# Environment Variables Reference

All configuration is done via environment variables. Copy `.env.example` → `.env` and fill in values.

## Backend (FastAPI)

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `DATABASE_URL` | Yes | `sqlite+aiosqlite:///./nexus.db` | Database connection URL (SQLite for dev, PostgreSQL for prod) |
| `AUTH_ENABLED` | No | `true` | Enable session-based auth. Set `false` for development without login. |
| `CORS_ORIGINS` | No | `http://localhost:3000` | Comma-separated allowed origins |
| `ANTHROPIC_API_KEY` | No | — | Anthropic API key for Claude models |
| `OPENAI_API_KEY` | No | — | OpenAI API key for GPT models |
| `REDIS_URL` | No | — | Redis connection URL. Enables distributed rate limiting & leader election. |
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
