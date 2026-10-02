# Production database roles

This runbook covers how NEXUS uses PostgreSQL roles in production, how to provision them, how
to run migrations, how to repair an installation whose application role owns the schema, and
how to check that the result is sound.

## Why roles are separated

In PostgreSQL the owner of a table can drop its triggers, disable or un-force row level
security (RLS), alter or drop its policies, change its constraints and drop the table. `FORCE
ROW LEVEL SECURITY` binds the owner to RLS policies for ordinary queries, but it does not stop
the owner from running DDL that removes the policies. NEXUS depends on append-only triggers,
tenant isolation policies and table constraints, so the role that serves requests must not own
any schema object. Those protections are only structural if the application role is unable to
change them, so ownership has to sit with a different role that the application never uses.

## Roles

| Role | Used by | Purpose | Attributes |
| --- | --- | --- | --- |
| `nexus_migrator` | Migration job only | Owns schema `public` and every table, sequence and function. Runs Alembic. | LOGIN, no SUPERUSER, no BYPASSRLS, no CREATEDB, no CREATEROLE |
| `nexus_app` | API, worker, scheduler (`DATABASE_URL`) | Runtime DML identity. Reads and writes rows. Owns nothing. | LOGIN, no SUPERUSER, no BYPASSRLS, no CREATEDB, no CREATEROLE, bound by RLS |
| `nexus_system` | Existing cross-tenant `system_session` callers (see "The system role today") | Privileged identity that bypasses RLS so it can see every tenant. Owns nothing. | LOGIN, BYPASSRLS, no SUPERUSER, no CREATEDB, no CREATEROLE |

None of the three is a member of another. `nexus_app` cannot `SET ROLE` to the migrator or the
system role.

Role names can be overridden with `nexus.migrator_role`, `nexus.app_role` and
`nexus.system_role` when provisioning, with `NEXUS_MIGRATION_ROLE`, `DATABASE_USER` and
`DATABASE_SYSTEM_USER` for the migration entry point.

### Privilege matrix

| Capability | `nexus_migrator` | `nexus_app` | `nexus_system` | PUBLIC |
| --- | --- | --- | --- | --- |
| Own tables, sequences, functions, schema `public` | yes | no | no | no |
| CREATE in schema `public` | yes | no | no | no |
| CREATE on the database | no | no | no | no |
| SELECT, INSERT, UPDATE, DELETE on tables | owner | yes | yes | no |
| USAGE, SELECT, UPDATE on sequences | owner | yes | yes | no |
| TRUNCATE, REFERENCES, TRIGGER on tables | owner | no | no | no |
| ALTER or DROP table, trigger, function, policy; change RLS | yes | no | no | no |
| Any access to `alembic_version` | owner | no | no | no |
| Bypass RLS | no | no | yes | no |

Default privileges on objects the migrator creates give `nexus_app` and `nexus_system` the DML
and sequence access above automatically. No migration names a role, so a table that a later
migration creates, or recreates after a downgrade and upgrade, is usable by the application
without further steps.

## Credential separation

Three credentials, three variables, never derived from one another:

| Variable | Role | Injected into |
| --- | --- | --- |
| `DATABASE_URL` | `nexus_app` | API, worker, scheduler |
| `MIGRATION_DATABASE_URL` | `nexus_migrator` | The migration job only |
| `SYSTEM_DATABASE_URL` | `nexus_system` | Production Compose: API, worker and scheduler (legacy carve-out). Helm: nothing. See "The system role today" |

### The system role today

`nexus_app` is the runtime DML identity. `nexus_migrator` owns schema objects and runs Alembic.
`nexus_system` is a privileged BYPASSRLS identity that the existing cross-tenant
`system_session` callers use. Those callers include the API lifespan startup tasks and the
orchestrator tick, and `system_session` refuses to run unless its connection has BYPASSRLS.

- **Production Compose** currently injects `SYSTEM_DATABASE_URL` into the API, worker and
  scheduler, through `.env.production`. This is an explicit legacy carve-out, not the desired
  final architecture. `DATABASE_URL` in those processes is still `nexus_app`, but a process that
  also holds a BYPASSRLS credential is not least-privileged: code or an attacker running in it
  can reach every tenant.
- **Helm** currently injects no `SYSTEM_DATABASE_URL` into any pod. The existing lifespan and
  orchestrator `system_session` paths can therefore fail their BYPASSRLS validation in Helm
  deployments. The chart does not fall back to `DATABASE_URL` for the system credential, and
  this document does not recommend adding the system credential to every pod.

Do not describe `nexus_system` as absent from the normal runtime processes while the Compose
carve-out stands. Both points are a production blocker for runtime least privilege; the
follow-up is described under "Deferred work: system-session process isolation".

Rules:

- Never build one URL by editing the user or password of another.
- Never put a password in a values file, a command line argument, a log line or a rendered
  document. Passwords travel as session settings in the environment (see below) or in a secret.
- The runtime refuses to start when `MIGRATION_DATABASE_URL` is present in its environment
  (`MIGRATION_CREDENTIAL_IN_RUNTIME`). That makes an accidental shared env file fail loudly.
- The migration entry point never reads `DATABASE_URL`. A missing migration URL is an error,
  not a fallback.
- Use a distinct password for each role. Use URL-safe alphanumeric passwords, since they pass
  through `PGOPTIONS`, where a space would split the option.

## Fresh provisioning

`deploy/postgres/provision-roles.sql` is the single source of the role model. An administrator
runs it once per database, and again after any change. It is idempotent: it creates missing
roles, rotates passwords only when a password setting is supplied, re-asserts role attributes,
removes memberships among the three roles, installs the `vector` extension, transfers schema
`public` to the migrator, removes CREATE from PUBLIC, and sets default privileges. The local
development bootstrap, `docker/postgres-init/01-init-roles.sql`, runs the same script with
throwaway passwords.

Passwords are passed as session settings so they never appear in an argument list:

```bash
export PGOPTIONS="-c nexus.migrator_password=$MIGRATOR_PW \
 -c nexus.app_password=$APP_PW \
 -c nexus.system_password=$SYSTEM_PW"
psql -v ON_ERROR_STOP=1 -d nexus -f deploy/postgres/provision-roles.sql
unset PGOPTIONS
```

On first provisioning all three password settings are required. On later runs omit them to
leave passwords alone, or supply one to rotate it.

The administrator must be a superuser, or on managed PostgreSQL an administrative role with
CREATEROLE that is a member of `nexus_migrator`, so it can transfer the schema and set default
privileges for objects the migrator creates. Granting `BYPASSRLS` to `nexus_system` needs
superuser-level rights. If the platform does not allow that, create the system role as the
platform's administrator permits. Do not weaken the other two roles to compensate.

## Managed PostgreSQL

For a managed service (a cloud database, or a PostgreSQL run by another team) the contract is:

1. An administrator creates the database and enables the `vector` extension. The migrator is
   not given database-level privileges, so the administrator creates the extension.
2. An administrator runs `provision-roles.sql` with the three passwords, as above.
3. The platform stores each connection URL in its secret manager under separate entries.
4. Nothing else grants `nexus_app` ownership, `CREATE`, membership in the migrator role, or any
   attribute listed as absent in the matrix.

The migration job checks this contract before it changes anything, and again afterwards. It
refuses (exit code 2) and names the roles involved, never a connection string, when:

- the connected identity is not the migration role, or is the application or system role;
- the migration role is a superuser or has BYPASSRLS, or lacks CREATE in schema `public`;
- the application role does not exist, has SUPERUSER, BYPASSRLS, CREATEROLE or CREATEDB, is a
  member of the migration role, or owns any schema object;
- `alembic_version` belongs to a role other than the migrator.

## Helm

The chart builds no database URL and holds no password.

1. Create a Secret in the release namespace with the key `MIGRATION_DATABASE_URL` holding the
   `nexus_migrator` URL. Create it with an external secret manager, an `ExternalSecret`
   managed outside this chart, or by an operator. It has to exist before the release, because
   the migration Job is a Helm pre-install and pre-upgrade hook, and hooks run before the
   chart's own Secret exists.
2. Point the chart at it:

   ```yaml
   migration:
     enabled: true
     user: nexus_migrator
     existingSecret: <name of that Secret>
     secretKey: MIGRATION_DATABASE_URL   # change only if your secret manager uses another key
   ```

3. Supply the runtime URL (`DATABASE_URL`, `nexus_app`) through the chart's existing secret
   mechanism. The Deployment receives only that URL.

The migration Job receives only the configuration map and `MIGRATION_DATABASE_URL`. The
Deployment receives only `DATABASE_URL`. Rendering fails, with no fallback, when:

- `migration.enabled` is true and `migration.existingSecret` or `migration.secretKey` is empty;
- `migration.user`, `database.user` and `database.systemUser` are not three different roles, so
  one principal would migrate and serve;
- `database.user` is `nexus_system` or `nexus_migrator`;
- `migration.user` is `nexus_app` or `nexus_system`;
- any of the three user values is empty.

`helm lint` and `helm template` in the deploy pipeline pass
`--set migration.existingSecret=nexus-migration-db` so they validate the chart shape without a
real Secret.

## Production Compose

`docker-compose.prod.yml` uses three env files, one per trust domain. Copy the examples and fill
them in; the real files are ignored by git.

| File | Holds | Read by |
| --- | --- | --- |
| `.env.postgres` (from `.env.postgres.example`) | Bootstrap administrator for the `postgres` service | `postgres` only |
| `.env.migration` (from `.env.migration.example`) | `MIGRATION_DATABASE_URL` | `migrate` only |
| `.env.production` (from `.env.production.example`) | `DATABASE_URL` and `SYSTEM_DATABASE_URL`, plus the rest of the runtime configuration | api, worker, scheduler |

Start order:

1. Start PostgreSQL: `docker compose -f docker-compose.prod.yml up -d postgres`. The image is
   `pgvector/pgvector`, because the migrations need the `vector` extension.
2. Provision the roles once, as the bootstrap administrator, with passwords in `PGOPTIONS`:

   ```bash
   export PGOPTIONS="-c nexus.migrator_password=$MIGRATOR_PW \
    -c nexus.app_password=$APP_PW \
    -c nexus.system_password=$SYSTEM_PW"
   docker compose -f docker-compose.prod.yml exec -T -e PGOPTIONS postgres \
     psql -U "$POSTGRES_USER" -d nexus -v ON_ERROR_STOP=1 \
     < deploy/postgres/provision-roles.sql
   unset PGOPTIONS
   ```

   `-e PGOPTIONS` without a value forwards the variable from your shell, so the secrets are not
   in the command line. `POSTGRES_USER` and `POSTGRES_DB` come from your `.env.postgres`.
3. Start the stack: `docker compose -f docker-compose.prod.yml up -d`. The `migrate` service
   runs `python -m nexus.db_migrate` as `nexus_migrator` and exits. The API, worker and
   scheduler declare `depends_on: migrate: condition: service_completed_successfully`, so they
   start only after a successful migration, and a refused preflight keeps them down.

Nothing creates roles or schema implicitly. Temporal in this file still takes its database
credentials from shell interpolation; it is outside the NEXUS role model.

## Running migrations

`python -m nexus.db_migrate` is the only supported production migration command. It:

1. reads `MIGRATION_DATABASE_URL` (a `postgresql+asyncpg` URL) and nothing else;
2. runs the preflight above;
3. runs `alembic upgrade head`;
4. revokes every privilege on `alembic_version` from PUBLIC, the application role and the
   system role, since the runtime has no use for it and a role that could rewrite it could
   make a later migration skip or repeat work;
5. runs the ownership check again and fails if the application role owns anything.

Exit code 0 means migrated and verified, 2 means refused, and any other non-zero code is an
Alembic or database error. Running `alembic` directly with a runtime credential is not
supported in production.

## Auditing and repairing an existing installation

Installations migrated by the old Helm job (which used the application credential) have tables
owned by `nexus_app`. `deploy/postgres/remediate-ownership.sql` moves ownership to the migrator
without touching data. Run it as an administrator, never from an application pod.

1. Provision first, so the migrator exists: run `provision-roles.sql` as above.
2. Take a backup. See "Rollback limits" below.
3. Dry run (the default). It changes nothing and prints one line per object:

   ```bash
   psql -v ON_ERROR_STOP=1 -d nexus -f deploy/postgres/remediate-ownership.sql
   ```

   - `[transfer]` objects in schema `public` owned by the application role, which will move:
     the schema, tables, partitioned tables, views, sequences, functions, procedures, enum
     and domain types. A sequence owned by a table column follows its table.
   - `[acl]` the privileges on a moved relation as they are now, which will be replaced.
   - `[manual]` anything that cannot be moved safely: the database itself, default privileges
     the application role set, objects in other schemas, and other object kinds. Resolve these
     by hand. The apply refuses while any `[manual]` item remains.
4. Apply, in one transaction:

   ```bash
   PGOPTIONS="-c nexus.remediation_mode=apply" \
     psql -v ON_ERROR_STOP=1 -d nexus -f deploy/postgres/remediate-ownership.sql
   ```

   It transfers each listed object with `ALTER ... OWNER TO`, resets the privileges on moved
   relations to what provisioning gives new objects, and checks at the end that the
   application role owns nothing and that `alembic_version` belongs to the migrator. If
   anything fails, the transaction rolls back and nothing has moved.
5. Re-run `provision-roles.sql` without password settings, then verify with the queries below.

What it deliberately does not do: it does not use `REASSIGN OWNED`, so objects the application
role owns outside NEXUS's scope are not swept in. It does not read or change rows. Indexes,
constraints, triggers, policies, `FORCE ROW LEVEL SECURITY` and the Alembic version are
preserved, because they stay with their table.

### Rollback limits

- The ownership change can be undone only by hand, with `ALTER ... OWNER TO` back to the
  previous owner. That restores the old, weaker state and is not a recommended repair.
- The previous privileges on a moved relation are replaced, not saved. The dry run's `[acl]`
  lines are the record, so keep that output with the change ticket.
- A restored backup also restores the old ownership.
- Never roll back by granting the application role ownership again.

## Verification SQL

Run these as an administrator. Substitute your role names if you overrode them.

Role attributes: expect `nexus_app` and `nexus_migrator` to show false for every column, and
`nexus_system` to show only `rolbypassrls` true.

```sql
SELECT rolname, rolsuper, rolbypassrls, rolcreatedb, rolcreaterole, rolreplication
  FROM pg_roles
 WHERE rolname IN ('nexus_migrator', 'nexus_app', 'nexus_system');
```

No memberships among the three: expect zero rows.

```sql
SELECT g.rolname AS granted, m.rolname AS member
  FROM pg_auth_members am
  JOIN pg_roles g ON g.oid = am.roleid
  JOIN pg_roles m ON m.oid = am.member
 WHERE g.rolname IN ('nexus_migrator', 'nexus_app', 'nexus_system')
   AND m.rolname IN ('nexus_migrator', 'nexus_app', 'nexus_system');
```

Ownership: expect every row to show `nexus_migrator`, and no row for `nexus_app`.

```sql
SELECT n.nspname, c.relname, c.relkind, pg_get_userbyid(c.relowner) AS owner
  FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
 WHERE n.nspname = 'public' AND c.relkind IN ('r', 'p', 'v', 'S')
 ORDER BY owner, c.relname;

SELECT nspname, pg_get_userbyid(nspowner) AS owner FROM pg_namespace WHERE nspname = 'public';

SELECT p.proname, pg_get_userbyid(p.proowner) AS owner
  FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace
 WHERE n.nspname = 'public' AND pg_get_userbyid(p.proowner) <> 'nexus_migrator';
```

Application role privileges: expect no table where `TRUNCATE`, `REFERENCES` or `TRIGGER` is
true, and no `alembic_version` row with any privilege true.

```sql
SELECT c.relname,
       has_table_privilege('nexus_app', c.oid, 'TRUNCATE')   AS truncate_,
       has_table_privilege('nexus_app', c.oid, 'REFERENCES') AS references_,
       has_table_privilege('nexus_app', c.oid, 'TRIGGER')    AS trigger_,
       has_table_privilege('nexus_app', c.oid, 'SELECT')     AS select_
  FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
 WHERE n.nspname = 'public' AND c.relkind IN ('r', 'p')
   AND (has_table_privilege('nexus_app', c.oid, 'TRUNCATE')
     OR has_table_privilege('nexus_app', c.oid, 'REFERENCES')
     OR has_table_privilege('nexus_app', c.oid, 'TRIGGER')
     OR c.relname = 'alembic_version');
```

Schema and database rights: expect false for CREATE for `nexus_app`, `nexus_system` and
PUBLIC (`has_schema_privilege('public', ...)` does not accept PUBLIC, so check the ACL).

```sql
SELECT has_schema_privilege('nexus_app', 'public', 'CREATE') AS app_schema_create,
       has_database_privilege('nexus_app', current_database(), 'CREATE') AS app_db_create;

SELECT nspacl FROM pg_namespace WHERE nspname = 'public';
SELECT datacl FROM pg_database WHERE datname = current_database();
```

The schema ACL should list `USAGE` for the application and system roles, and no `C` for anyone
but the owner. PostgreSQL grants PUBLIC `USAGE` on schema `public` by default and this
runbook does not change that.

Protections still in place: expect every protected table to show both flags true, and the
append-only triggers to be listed.

```sql
SELECT relname, relrowsecurity, relforcerowsecurity
  FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
 WHERE n.nspname = 'public' AND c.relkind = 'r' AND c.relrowsecurity
 ORDER BY relname;

SELECT event_object_table, trigger_name FROM information_schema.triggers
 WHERE trigger_schema = 'public' ORDER BY 1, 2;
```

Default privileges for new objects:

```sql
SELECT pg_get_userbyid(defaclrole) AS grantor, defaclobjtype, defaclacl
  FROM pg_default_acl;
```

Application-role behaviour check. Connect as `nexus_app` and expect each statement to fail
with SQLSTATE 42501 (`must be owner of ...` or `permission denied`):

```sql
DROP TRIGGER IF EXISTS some_trigger ON some_table;      -- must be owner
ALTER TABLE some_table NO FORCE ROW LEVEL SECURITY;     -- must be owner
TRUNCATE some_table;                                    -- permission denied
SET ROLE nexus_migrator;                                -- permission denied
```

Use a table and trigger that exist in your database. `tests/test_db_role_separation_postgres.py`
automates these checks against a fresh database.

## Rotation

Rotate one role at a time, and rotate the migrator and system credentials on their own schedule.

1. Generate a new URL-safe password and store it in the secret manager as a new version.
2. Run `provision-roles.sql` with only that role's password setting. It changes that role's
   password and leaves the others alone.
3. Roll the consumers: restart the Deployment (for `nexus_app`), or re-run the migration job
   (for `nexus_migrator`) so each picks up the new secret.
4. Confirm a connection with the new secret, then revoke the old secret version.

Rotating `nexus_app` briefly interrupts pods that still hold the old password, so roll the
Deployment right after the change.

## Incident response

If a credential may be exposed:

- `nexus_app` credential: rotate it at once. The role owns nothing and cannot alter the schema,
  but it can read and write tenant rows that RLS allows for a tenant it can set. Rotate, then
  review the audit log for the window.
- `MIGRATION_DATABASE_URL`: treat as high impact. This role owns the schema and can drop
  triggers and policies. Rotate at once, then run the verification SQL and compare triggers,
  policies, RLS flags and constraints against a known-good environment, and review recent DDL
  in the PostgreSQL log if it is enabled. Check that `MIGRATION_DATABASE_URL` is not set on any
  runtime pod; the runtime refuses to start with it, so a running pod without it is expected.
- `nexus_system` credential: rotate at once. The role bypasses RLS, so treat it as access to
  every tenant, and review the audit log for the window.
- A runtime process that starts with `MIGRATION_CREDENTIAL_IN_RUNTIME`: the migrator credential
  reached an application environment. Remove it from that environment and treat the credential
  as exposed.
- Application role found to own an object: run the legacy audit and, after reviewing the dry
  run, the remediation.

## Known limitations

- PUBLIC keeps the PostgreSQL default `USAGE` on schema `public`, and the default `EXECUTE` on
  functions. The grant of `UPDATE` on sequences is retained for compatibility.
- Evidence-table grants are not narrowed. The runtime role has the same DML on every table, and
  the evidence tables could be narrowed to the access they need without naming a role in a
  migration. That is a follow-up.
- Production blocker: runtime system-role isolation is not done. Production Compose gives the
  API, worker and scheduler `SYSTEM_DATABASE_URL`, and Helm gives no pod one, so the
  `system_session` paths may fail in Helm. See "The system role today". This change separates
  schema ownership and the migration identity; it does not make the runtime least-privileged.
- The ownership preflight runs in the migration job. The runtime performs no ownership check
  beyond refusing to hold the migrator credential.
- Remediation replaces privileges on moved relations and cannot restore the previous ones
  automatically.
- Provisioning needs an administrator that can transfer the schema, and `BYPASSRLS` for the
  system role needs superuser-level rights. Some managed services do not allow that.

## Deferred work: system-session process isolation

Not implemented here. This is the design record for the next change, which must be a separate
pull request that audits every `system_session` caller before moving it.

Target architecture:

- The API receives only `DATABASE_URL` (`nexus_app`).
- Ordinary workers receive only `DATABASE_URL` (`nexus_app`).
- Cross-tenant discovery and control-plane work runs in a dedicated internal process that holds
  `SYSTEM_DATABASE_URL` (`nexus_system`). That process has no public ingress.
- The scheduler or system dispatcher may discover tenant ids with `nexus_system`, but tenant
  work runs through tenant-bound `nexus_app` sessions wherever possible.
- Startup checks that need privileged access move out of the public API lifespan.
- Helm and production Compose wire the system credential only to the dedicated privileged
  process.
- No fallback to the application or migrator credential.
- Tests prove that the API and ordinary worker environments contain no system credential.
