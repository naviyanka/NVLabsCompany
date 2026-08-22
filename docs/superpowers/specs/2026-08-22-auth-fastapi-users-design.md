# Design: Authentication and Tenant Identity via fastapi-users

**Date:** 2026-08-22
**Status:** Approved design, pending implementation plan
**Related plan items:** POL-16-A (login page), FIX-04-B (tenant filters, 404 on cross-tenant), FIX-04-C (tenant middleware)

## Problem

NEXUS has no authentication. Every request's tenant is taken from a client-supplied `X-Company-Id` header, trusted verbatim in two places:

- `src/nexus/api/deps.py:20` — `get_current_company_id` parses the header and returns it as the company for the request. All 35 routers consume this through the `CurrentCompanyId` alias.
- `src/nexus/api/middleware.py:101` — `GovernanceMiddleware` parses the same header before deciding the kill switch, tenant scope, rate limit, policy evaluation, and budget pre-check.

Any client that sets that header inherits any tenant's agents, tasks, budgets, secrets, and provider credentials, and can also select which company's kill switch and budget it is measured against. Supporting evidence of the gap:

- `python-jose[cryptography]` and `passlib[bcrypt]` are declared in `pyproject.toml` and imported nowhere in `src/`.
- `src/nexus/models/user_profile.py` defines `UserProfile` and `UserSession` with no password hash and no token column.
- `src/nexus/api/routes/profile.py:96` `change_password` returns `{"success": True}` without verifying or storing anything.
- `src/nexus/api/routes/profile.py:65` `get_profile` selects a profile by `company_id` alone — the schema models one profile per company, with no concept of a user.
- The dashboard sends a hardcoded constant: `dashboard/src/config.ts:7` `COMPANY_ID`, attached by `dashboard/src/api/client.ts:20`.

This design adds authentication and identity, makes the existing governance gates trustworthy, and enforces authorization on the highest-risk routes. It reuses the governance primitives already in the repo (`RBACManager`, `STANDARD_ROLES`, `TenantGuard`) rather than duplicating them.

## Decisions

Settled during brainstorming, recorded here because each one constrains the implementation:

| Decision | Choice |
| --- | --- |
| Principals | Human operators **and** service tokens |
| User ↔ company | Many companies per user, via a membership table |
| Session representation | Database-backed token in an httpOnly cookie |
| Onboarding | Invite-only; no public registration |
| Authorization scope | Roles enforced on sensitive routes only, not all 35 |
| Service token shape | Company-scoped key carrying its own role |
| Rollout | `AUTH_ENABLED` flag, default on, removed after cutover |
| Library | fastapi-users 15.0.5 (MIT) |

### Why fastapi-users over an external identity provider

Zitadel, Keycloak, Authentik, and Logto all ship their own role and permission models. This repo already has `RBACManager`, `Permission`, `Role`, and `STANDARD_ROLES` in `src/nexus/governance/rbac.py`, plus `TenantGuard` for tenant scoping. Adopting an external IdP would mean either running two authorization systems or discarding working code and operating a second service. fastapi-users is a library, not a service: it supplies password hashing, a user manager, and router shapes, and leaves authorization to the application.

### Chosen integration approach: authentication as middleware

Three approaches were considered. The deciding constraint is that `GovernanceMiddleware` runs before any route dependency, so nothing resolved at dependency level can make the kill switch, policy, or budget gates trustworthy.

- **A — authentication in middleware (chosen).** A new `AuthenticationMiddleware` wraps `GovernanceMiddleware`, resolves the credential once, and publishes a `Principal` on the ASGI scope. Governance reads the principal instead of the header. `deps.py` rebuilds `CurrentCompanyId` from scope state, so all 35 routers stay unchanged. Cost: the middleware opens its own database session, adding one SELECT per request, and needs a public-path allowlist.
- **B — authentication in dependencies only.** `deps.py` resolves the principal via `Depends(get_db)`; the governance middleware is demoted to non-security work and its kill switch and budget checks move into a dependency attached at `include_router` time. More idiomatic FastAPI and easier to override in tests, but it rewrites the purpose of the governance middleware, touches all 35 `include_router` calls, and moves the gates to after routing and validation.
- **C — signed cookie payload with split verification.** The cookie carries a signed `{session_id, user_id, active_company_id}`; the middleware verifies only the signature, and the dependency performs the database revocation check. Avoids the extra SELECT, but requires a custom fastapi-users strategy in place of anything stock, and lets governance act on a revoked-but-unexpired session.

A was chosen: smallest blast radius on route code, keeps stock library pieces, and is the only option that fixes the governance gates without restructuring them. One extra indexed SELECT per request is a fair price for closing the tenant-spoofing hole.

## Data model

fastapi-users' `SQLAlchemyBaseUserTableUUID` is a SQLAlchemy 2.0 `DeclarativeBase` model, while this repo is entirely SQLModel. The two are reconciled by sharing one `MetaData`, so Alembic autogeneration and the SQLite `create_all` in `lifespan` see the auth tables alongside the existing 22:

```python
class AuthBase(DeclarativeBase):
    metadata = SQLModel.metadata
```

### New tables

**`users`** — fastapi-users `SQLAlchemyBaseUserTableUUID`: `id`, `email` (unique), `hashed_password`, `is_active`, `is_superuser`, `is_verified`; plus `created_at` and `last_login_at`. Deliberately **no `company_id`** — membership owns the user-to-company relationship.

**`company_memberships`** — `id`, `user_id` → `users.id`, `company_id` → `companies.id`, `role` (one of the `STANDARD_ROLES` names: `admin`, `manager`, `agent`, `viewer`), `invited_by` → `users.id` (nullable), `created_at`. Unique constraint on `(user_id, company_id)`.

**`api_keys`** — `id`, `company_id` → `companies.id`, `name`, `key_prefix` (display only, e.g. `nxs_a1b2c3d4`), `key_hash` (unique, indexed), `role`, `created_by` → `users.id` (nullable), `expires_at`, `last_used_at`, `revoked_at` (all nullable), `created_at`.

**`company_invites`** — `id`, `company_id` → `companies.id`, `email`, `role`, `token_hash` (unique), `invited_by` → `users.id`, `expires_at`, `accepted_at` (nullable), `created_at`.

### Changed tables

**`user_sessions`** — repurposed as the session-token table.

- `user_id` foreign key moves from `user_profiles.id` to `users.id`.
- `company_id` is renamed `active_company_id`; this is the pinned company for the session, and company switching updates this column.
- New: `token_hash` (unique, indexed), `expires_at`, `revoked_at` (nullable).
- `is_current` is **dropped**. It cannot be a stored column, because its meaning is "the session making this request". It is computed at read time by comparing the request's token hash.

**`user_profiles`** — becomes per-human identity rather than per-company.

- `company_id` is dropped.
- `user_id` → `users.id` (unique) is added.
- `src/nexus/api/routes/profile.py` is rewritten to read the principal instead of a path parameter. `get_profile` stops fabricating a default identity on a miss, `change_password` gains a real implementation using the fastapi-users password helper, and `list_sessions` — currently filtered by an unauthenticated path parameter — is superseded by `GET /api/v1/auth/sessions`.

### Hashing

Passwords use the fastapi-users password helper (v15 ships `pwdlib`, Argon2 by default). Session tokens, API keys, and invite tokens are `secrets.token_urlsafe(32)` values stored as SHA-256 digests, because they are looked up on every request and an Argon2 verification in that path would be prohibitive. The raw secret is shown to the caller exactly once at creation.

Consequence: `python-jose[cryptography]` and `passlib[bcrypt]` are removed from `pyproject.toml`. Both are currently unused.

### Migration

A single Alembic revision. The foreign key repoint and the dropped columns mean existing `user_profiles` and `user_sessions` rows are dropped rather than backfilled; the only rows today come from the demo seed.

## Principal resolution

```python
@dataclass(frozen=True)
class Principal:
    kind: Literal["user", "service"]
    subject_id: uuid.UUID          # user_id, or api_key_id for service callers
    company_id: uuid.UUID          # the active company
    role: str                      # a STANDARD_ROLES name
    session_id: uuid.UUID | None
    is_superuser: bool = False
```

`AuthenticationMiddleware` handles both `http` and `websocket` scopes. Server-sent events and `/ws/{client_id}` both rely on the session cookie, so skipping websocket scopes would leave the WebSocket endpoint reading an empty principal.

Resolution order:

1. Path in `PUBLIC_PATHS` (`/api/v1/auth/login`, `/api/v1/auth/invite/accept`, `/health/*`, `/docs`, `/openapi.json`, `/metrics`) — pass through with no principal.
2. `Authorization: Bearer nxs_...` — SHA-256 the secret, one SELECT on `api_keys.key_hash`, reject on `revoked_at` or `expires_at`, yielding `Principal(kind="service", role=key.role, company_id=key.company_id)`.
3. Cookie `nexus_session` — SHA-256, then **one** SELECT joining `user_sessions`, `users`, and `company_memberships` on `(user_id, active_company_id)`. That single row supplies expiry, `is_active`, and the role.
4. No credential and `settings.auth_enabled` — `401 AUTH_REQUIRED`; for websocket scopes, close with `1008`.
5. No credential and the flag off — legacy `X-Company-Id` path, producing `Principal(kind="service", role="admin", ...)`.
6. Publish the principal on `scope["state"]["principal"]`.

The middleware opens a session from `async_session_maker()` and closes it before calling the inner application. Writes to `last_used_at` and `last_active_at` are throttled to at most once per 60 seconds per token, so the steady state is one SELECT and no write per request.

If the membership row is gone while a session is still live — the user was removed from the company — the response is `401` and that session is revoked.

### Governance middleware

The header parse at `src/nexus/api/middleware.py:101-107` is deleted. `company_id` comes from `scope["state"]["principal"]`. Because authentication sits outside governance, the principal is always resolved before the kill switch, tenant scope, policy evaluation, and budget pre-check run. Those four gates stop being spoofable, which is the primary security outcome of this design.

### Middleware order

Starlette makes the last-added middleware the outermost one, so `add_middleware` order in `main.py` is the reverse of execution order. Two constraints apply: authentication must wrap governance, and CORS must wrap everything.

| | Source order (`add_middleware` calls) | Execution order (outermost first) |
| --- | --- | --- |
| Today | CORS, Governance, APIVersion, Metrics, RequestID | RequestID, Metrics, APIVersion, Governance, CORS |
| After | Governance, **Auth**, APIVersion, Metrics, RequestID, CORS | CORS, RequestID, Metrics, APIVersion, **Auth**, Governance |

`Auth` is added immediately after `Governance` so it sits directly outside it, and governance can rely on `scope["state"]["principal"]` already being populated.

Moving CORS to last-added fixes a pre-existing bug. CORS is currently added first, i.e. innermost, so today's `403 POLICY_DENIED` responses carry no CORS headers and a browser sees an opaque network error rather than the status. New `401` responses would inherit the same defect.

### Dependency surface

`src/nexus/api/deps.py` gains `CurrentPrincipal`, `CurrentUserId`, and `require_permission(resource, action)`. Critically, `CurrentCompanyId` keeps both its name and its `uuid.UUID` type, now sourced from `principal.company_id`. All 35 routers are unchanged by this substitution.

Note on impact analysis: `impact({target: "get_current_company_id", direction: "upstream"})` reports zero callers and LOW risk. That is a false negative — the graph does not traverse `Depends()` indirection through an `Annotated` alias. The real fan-in is every router importing `CurrentCompanyId`.

### CSRF

Forced by the cookie choice. Login sets a second, non-httpOnly `nexus_csrf` cookie; the dashboard echoes its value in an `X-CSRF-Token` header; the middleware requires a match on `POST`, `PUT`, `PATCH`, and `DELETE` **for cookie-authenticated requests only**. API-key callers send no cookie and therefore have no CSRF surface. Session cookie flags: `httpOnly`, `SameSite=Lax`, and `Secure` outside development.

### CORS

Also forced rather than optional. `allow_credentials=True` is illegal in combination with a wildcard origin, so the permissive configuration flagged in `docs/PRODUCTION-READINESS-AUDIT.md:358` is replaced by an explicit configured origin list.

## Module layout

New package `src/nexus/auth/`:

| File | Contents |
| --- | --- |
| `models.py` | `AuthBase`, `User`, `CompanyMembership`, `ApiKey`, `CompanyInvite` |
| `principal.py` | `Principal`, `PUBLIC_PATHS` |
| `middleware.py` | `AuthenticationMiddleware` |
| `manager.py` | fastapi-users `UserManager`, password helper, `on_after_*` hooks |
| `session_strategy.py` | `Strategy` implementation over `user_sessions` |
| `keys.py` | API key mint, verify, revoke |
| `invites.py` | Invite create and accept |
| `routes.py` | The auth router |
| `bootstrap.py` | First-admin creation command |

On `session_strategy.py`: the stock `DatabaseStrategy` expects fastapi-users' own `accesstoken` table holding the raw token, reached through an `AccessTokenDatabase` adapter. Our table stores a hash and carries `active_company_id`. Rather than contort the adapter, we implement `Strategy[User, uuid.UUID]` directly — three methods: `write_token`, `read_token`, `destroy_token`. fastapi-users still supplies password hashing, the `UserManager`, and the login and logout router shapes.

## Endpoints

All under `/api/v1/`:

```
POST   auth/login                  sets nexus_session + nexus_csrf; returns user, profile, memberships
POST   auth/logout                 revokes the session row, clears cookies
GET    auth/me                     principal, user, profile, memberships
POST   auth/switch-company         {company_id}; validates membership, updates active_company_id
POST   auth/change-password        replaces the profile.py stub
GET    auth/sessions               own sessions, with is_current computed
DELETE auth/sessions/{id}          revoke one of your own sessions
POST   auth/invite/accept          PUBLIC: {token, password, first_name, last_name}
GET    companies/{cid}/invites     admin
POST   companies/{cid}/invites     admin: {email, role}
DELETE invites/{id}                admin
GET    companies/{cid}/api-keys    admin; prefix and metadata only
POST   companies/{cid}/api-keys    admin; the full secret is returned exactly once
DELETE api-keys/{id}               admin
```

### No mailer, and what follows from that

The repository has no email infrastructure. An invite response therefore returns the token to the creating administrator, who delivers the link out of band.

`forgot-password` and `reset-password` are **out of scope for this pass**. Without email delivery, the only way to return a reset token is to an anonymous caller, which is an account-takeover primitive rather than a feature. Authenticated `change-password` covers the real need. The mailer seam is left for a later pass, at which point the fastapi-users reset router can be mounted as intended.

## Authorization

Role guards land on eight route files: `secrets`, `budgets`, `policies`, `approvals`, `incidents` (kill switch), `control`, `evolution` (promotion), and `adapters` (provider credentials), plus the administrative endpoints above. Guards are attached per route rather than per router, because read and write permissions differ by method. The remaining 27 routers receive authentication and tenant scoping only.

`require_permission` does **not** mutate `RBACManager._actor_permissions`. That attribute is a process-global dictionary, and a per-request write to it would race across concurrent requests. Instead the dependency resolves the principal's role name against `STANDARD_ROLES` and reuses `_permission_matches` as a pure check. Denial is `403 PERMISSION_DENIED`.

## Frontend

### Modified

- `dashboard/src/api/client.ts` — `credentials: 'include'` on all five methods. `defaultHeaders()` loses `X-Company-Id` and gains `X-CSRF-Token`, read from the non-httpOnly `nexus_csrf` cookie, on mutating methods only. `handleResponse` gains a 401 branch that fires a registered `onUnauthorized` callback — registered by `AuthContext` rather than imported, to avoid a client-to-context import cycle — which clears state and routes to `/login`.
- `dashboard/src/api/events.ts` — `credentials: 'include'` on the stream fetch at line 63; the `X-Company-Id` header is dropped. This client streams via `fetch` and `ReadableStream` rather than `EventSource`, so no `withCredentials` handling is needed.
- `dashboard/src/config.ts` — `COMPANY_ID` is deleted. Its importers (`api/client.ts`, `api/repositories.ts`, `hooks/useOffice.ts`) switch to `activeCompanyId` from context. `useOffice` takes a `companyId` argument, matching the existing shape of `useAgents`, and `repositories.ts` loses its `= COMPANY_ID` default parameter so callers pass it explicitly.
- `dashboard/src/App.tsx` — wrapped in `AuthProvider`. `/login` and `/invite/accept` are public; every other route sits behind `RequireAuth`.
- `dashboard/src/pages/Settings.tsx` — sections for active sessions with revoke, API keys (the secret is shown once at creation, thereafter only the prefix), and invites for administrators.
- Layout header — a company switcher, rendered only when the user holds more than one membership.

### New

`context/AuthContext.tsx`, `hooks/useAuth.ts`, `api/auth.ts`, `pages/LoginPage.tsx`, `pages/AcceptInvitePage.tsx`, `components/RequireAuth.tsx`.

### Bootstrap and session lifetime

`AuthProvider` mounts and calls `GET /api/v1/auth/me`. A 200 populates user, profile, memberships, and `activeCompanyId`; a 401 renders the login page. Because the session cookie is httpOnly, no token ever exists in JavaScript — there is nothing to store and nothing to refresh.

This deviates from POL-16-A, which asks for a client-side refresh before expiry. With database-backed sessions the equivalent is server-side sliding expiry: `last_active_at` bumps extend the window, and the client only sees a 401 when the session is genuinely dead. No refresh endpoint and no browser timer.

## Error handling

| Case | Response |
| --- | --- |
| No credential, `auth_enabled` on | `401 AUTH_REQUIRED` |
| Session expired or revoked | `401 SESSION_EXPIRED`, cookies cleared |
| Unknown email, wrong password, or inactive user | `401 INVALID_CREDENTIALS`, one identical body |
| CSRF header missing or mismatched | `403 CSRF_FAILED` |
| Role lacks the permission | `403 PERMISSION_DENIED` |
| Resource belongs to another company | `404` — per FIX-04-B, never 403 |
| `switch-company` to a company without membership | `404`, same leakage rule |
| Invite token invalid, expired, or already used | `400 INVALID_INVITE`, one identical body |
| API key revoked or expired | `401 AUTH_REQUIRED` |
| Any websocket authentication failure | close `1008` |

Two requirements that are easy to overlook and are therefore stated explicitly:

- **User enumeration.** Login performs a password verification against a fixed dummy hash when the email does not exist, so the unknown-email and wrong-password paths cost comparable time as well as returning identical bodies.
- **Cross-site WebSocket hijacking.** WebSockets are not covered by CORS, so a cookie-authenticated `/ws/{client_id}` would otherwise be reachable from any origin. The middleware validates the `Origin` header against the configured allowlist for websocket scopes and closes `1008` on mismatch.

**Login brute force.** The existing rate limiter is keyed per company, and a login request has no company yet. A per-`(ip, email)` throttle is added — five failures per fifteen minutes — Redis-backed when Redis is available, with an in-process fallback.

## Configuration

New settings in `src/nexus/config.py`: `auth_enabled`, `session_ttl_hours`, `cookie_secure`, `cookie_domain`, `cors_allow_origins`, `login_max_attempts`, `login_window_minutes`.

`validate_config()` gains a check that fails loudly when `auth_enabled` is on and `cors_allow_origins` is a wildcard, since that combination is both illegal with credentialed requests and a CSRF hazard.

## Testing

`tests/conftest.py` gains four fixtures: a real in-memory SQLite `db_session`, an `app_client` built on httpx `ASGITransport`, an `auth_client` that is logged in with a primed cookie jar, and a `service_client` authenticated by API key. The existing `AsyncMock` fixtures are left exactly as they are so the roughly one hundred unit-test modules do not move.

New `tests/test_auth_*.py` modules cover: login and logout; session expiry and revocation; CSRF enforced for cookie callers and exempt for API keys; API key lifecycle; invite acceptance; the `switch-company` membership check; a cross-tenant read returning 404; `403 PERMISSION_DENIED`; the public-path allowlist; the `auth_enabled=False` legacy path; websocket origin rejection; and identical responses for unknown-email versus wrong-password.

`tests/test_realtime_sse.py:194-216` is the only existing test that sends `X-Company-Id`; it migrates to `auth_client`. Ten test files currently use an HTTP client at all, so the migration surface is small.

`e2e/example.spec.ts` is still the stock Playwright scaffold pointed at playwright.dev. It is replaced by a login, dashboard, logout specification — the first real application coverage in that directory.

## Rollout

Four commits, in order:

1. **Backend.** Models, the Alembic revision, the `auth/` package, middleware, `deps.py`, the eight RBAC-guarded route files, and backend tests. `AUTH_ENABLED` defaults on, and a local `.env` can turn it off so the un-migrated dashboard still runs.
2. **Bootstrap.** Invite-only onboarding means there must be a first administrator, so `python -m nexus.auth.bootstrap --email --password` creates the user plus an admin membership for the default company `00000000-0000-4000-8000-000000000001`. Without this step nobody can ever log in.
3. **Frontend.** Login, invite acceptance, `AuthContext`, `RequireAuth`, the `config.ts` `COMPANY_ID` removal, Settings sections, the company switcher, and the e2e specification.
4. **Cleanup.** Delete the legacy `X-Company-Id` branch and the `AUTH_ENABLED` flag.

Per the project's `CLAUDE.md`, `detect_changes({scope: "compare", base_ref: "main"})` runs before each commit.

## Out of scope

- Password reset by email, and any mailer. Blocked on there being no email infrastructure; see the endpoint section for why a tokened reset endpoint without delivery is unsafe.
- OAuth and social login. fastapi-users supports it via `SQLAlchemyBaseOAuthAccountTableUUID`, and the `users` table shape chosen here leaves room for it, but no provider is required yet.
- Two-factor authentication. `user_profiles.two_factor_enabled` already exists as a flag and stays decorative; the `toggle_two_factor` endpoint continues to only set the column.
- Full RBAC across all 35 routers. Twenty-seven routers get authentication and tenant scoping without role checks.
- Agents as first-class authenticating principals. Service tokens are company-scoped, not agent-scoped.
- Refactoring `RBACManager` off its in-memory `_actor_permissions` dictionary. This design routes around it rather than through it.

## Known risks

- **One extra SELECT per request** is accepted for every authenticated route. Indexed lookup on a hash column, but it is a new floor on request latency.
- **The middleware owns its own database session**, separate from the request-scoped `get_db`. If it leaks sessions under error paths, the pool drains; the implementation must close it in a `finally`.
- **The `AUTH_ENABLED` flag is a live tenant-spoofing bypass** while it exists. Commit 4 is not optional cleanup, and the flag should not survive into a deployed configuration.
- **Dropping `user_profiles.company_id` and `user_sessions.is_current`** is destructive. Only demo-seeded rows exist today, which is exactly the assumption to re-verify before running the migration anywhere else.
