"""Deployment guards for database role separation.

The application role must not own the schema, so the credentials must never collapse into
one: the migration job holds only the migrator credential, the runtime holds only the
application (and system) credentials, and nothing falls back from one to the other. These
checks read the chart, the Compose files and the SQL bootstrap, with no database needed. The
PostgreSQL behaviour is proved in ``test_db_role_separation_postgres.py``.
"""

import re
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

from nexus import db_migrate
from nexus.config_validator import ConfigurationError, enforce_no_migration_credential

ROOT = Path(__file__).resolve().parent.parent
CHART = ROOT / "deploy" / "helm" / "nexus"
TEMPLATES = CHART / "templates"
APP_ROLE, MIGRATOR_ROLE, SYSTEM_ROLE = "nexus_app", "nexus_migrator", "nexus_system"


def _text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _without_comments(sql: str) -> str:
    return "\n".join(line for line in sql.splitlines() if not line.lstrip().startswith("--"))


# --- Helm ------------------------------------------------------------------------------


def test_migration_job_uses_only_the_migration_credential():
    job = _text(TEMPLATES / "migration-job.yaml")
    assert "nexus.db_migrate" in job
    assert "alembic" not in job.replace("alembic-upgrade", "")
    assert not re.search(r"(?<![A-Z_])DATABASE_URL", job), "the job must not reference DATABASE_URL"
    assert "SYSTEM_DATABASE_URL" not in job
    assert "-secrets" not in job and "secretRef" not in job, "the job must not load the app Secret"
    assert re.search(r"name: MIGRATION_DATABASE_URL\s+valueFrom:\s+secretKeyRef:", job)
    assert ".Values.migration.existingSecret" in job and ".Values.migration.secretKey" in job
    assert "default" not in re.search(r"existingSecret[^\n]*", job).group(0), "no fallback secret"


@pytest.mark.parametrize(
    "name",
    [
        "api-deployment.yaml",
        "worker-deployment.yaml",
        "scheduler-deployment.yaml",
        "configmap.yaml",
        "secrets.yaml",
    ],
)
def test_runtime_templates_never_see_the_migrator_credential(name):
    text = _text(TEMPLATES / name)
    for forbidden in (
        "MIGRATION_DATABASE_URL",
        "migration.existingSecret",
        "migration.secretKey",
        "migration.user",
    ):
        assert forbidden not in text, f"{name} mentions {forbidden}"


def test_the_app_secret_holds_the_application_credential_only():
    text = _text(TEMPLATES / "secrets.yaml")
    assert re.search(r"DATABASE_URL: .*\.Values\.database\.user", text)
    assert ".Values.database.systemUser" not in text, (
        "the system credential is not injected into pods"
    )


def test_migration_values_default_to_no_secret_and_a_distinct_role():
    values = yaml.safe_load(_text(CHART / "values.yaml"))
    assert values["migration"]["existingSecret"] == "", (
        "an unset secret must fail closed, not default"
    )
    assert values["migration"]["user"] == MIGRATOR_ROLE
    assert values["database"]["user"] == APP_ROLE
    assert values["database"]["systemUser"] == SYSTEM_ROLE
    assert (
        len(
            {
                values["migration"]["user"],
                values["database"]["user"],
                values["database"]["systemUser"],
            }
        )
        == 3
    )


def test_the_chart_validates_the_roles_in_the_configmap():
    assert 'include "nexus.validateDatabaseRoles"' in _text(TEMPLATES / "configmap.yaml")
    helpers = _text(TEMPLATES / "_helpers.tpl")
    block = helpers[helpers.index('define "nexus.validateDatabaseRoles"') :]
    for needle in ("fail", "migration.user", "database.user", "database.systemUser", "required"):
        assert needle in block


helm = pytest.mark.skipif(shutil.which("helm") is None, reason="helm is not installed")


def _render(*sets: str) -> subprocess.CompletedProcess:
    args = ["helm", "template", "t", str(CHART)]
    for s in sets:
        args += ["--set", s]
    return subprocess.run(args, capture_output=True, text=True, check=False)


@helm
def test_helm_render_is_fail_closed_and_refuses_collapsed_identities():
    good = ("migration.existingSecret=migration-db",)
    ok = _render(*good)
    assert ok.returncode == 0, ok.stderr
    docs = [d for d in yaml.safe_load_all(ok.stdout) if d]
    job = next(d for d in docs if d["kind"] == "Job")
    env = job["spec"]["template"]["spec"]["containers"][0]["env"]
    url = next(e for e in env if e["name"] == "MIGRATION_DATABASE_URL")
    assert url["valueFrom"]["secretKeyRef"]["name"] == "migration-db"
    for d in docs:
        if d["kind"] == "Deployment":
            assert "MIGRATION_DATABASE_URL" not in yaml.safe_dump(d)

    refused = {
        "no migration secret": ("migration.existingSecret=",),
        "migrator is the app": (*good, "migration.user=nexus_app", "database.user=nexus_app"),
        "app is the migrator": (*good, "database.user=nexus_migrator"),
        "app is the system role": (*good, "database.user=nexus_system"),
        "migrator is the system role": (*good, "migration.user=nexus_system"),
        "same user for app and migration": (*good, "migration.user=app_x", "database.user=app_x"),
    }
    for label, sets in refused.items():
        result = _render(*sets)
        assert result.returncode != 0, f"{label} rendered"
        assert "migration-db" not in result.stdout


# --- Compose ---------------------------------------------------------------------------


def _compose(name: str) -> dict:
    return yaml.safe_load(_text(ROOT / name))["services"]


def _env_files(service: dict) -> list[str]:
    files = service.get("env_file", [])
    return [files] if isinstance(files, str) else list(files)


def test_prod_compose_migrates_once_as_the_migrator_before_the_runtime_starts():
    services = _compose("docker-compose.prod.yml")
    migrate = services["migrate"]
    assert migrate["command"] == ["python", "-m", "nexus.db_migrate"]
    assert migrate["restart"] == "no"
    assert _env_files(migrate) == [".env.migration"]
    assert migrate["depends_on"]["postgres"]["condition"] == "service_healthy"
    for name in ("api", "worker", "scheduler"):
        assert (
            services[name]["depends_on"]["migrate"]["condition"] == "service_completed_successfully"
        ), name


def test_prod_compose_keeps_the_credentials_apart():
    services = _compose("docker-compose.prod.yml")
    for name, service in services.items():
        files = _env_files(service)
        env = yaml.safe_dump(service.get("environment", {}))
        if name != "migrate":
            assert ".env.migration" not in files, f"{name} loads the migrator credential"
            assert "MIGRATION_DATABASE_URL" not in env, name
        if name in ("api", "worker", "scheduler"):
            assert files == [".env.production"], name
            assert "alembic" not in yaml.safe_dump(service.get("command", "")), (
                f"{name} runs migrations"
            )
        if name != "postgres":
            assert ".env.postgres" not in files, f"{name} loads the bootstrap superuser"
    assert _env_files(services["postgres"]) == [".env.postgres"]
    assert not any("initdb.d" in str(v) for v in services["postgres"].get("volumes", [])), (
        "production roles are provisioned by an administrator, not by a mounted init script"
    )
    assert services["postgres"]["image"].startswith("pgvector/pgvector"), (
        "the migrations need pgvector"
    )


def test_env_examples_keep_the_credentials_apart():
    runtime = _text(ROOT / ".env.production.example")
    assert "MIGRATION_DATABASE_URL" not in re.sub(r"(?m)^#.*$", "", runtime)
    assert not re.search(r"(?m)^POSTGRES_PASSWORD=", runtime)
    assert re.search(rf"(?m)^DATABASE_URL=postgresql\+asyncpg://{APP_ROLE}:", runtime)
    assert re.search(rf"(?m)^SYSTEM_DATABASE_URL=postgresql\+asyncpg://{SYSTEM_ROLE}:", runtime)
    assert "DATABASE_SYSTEM_URL" not in runtime, (
        "the variable the application reads is SYSTEM_DATABASE_URL"
    )

    migration = _text(ROOT / ".env.migration.example")
    assert re.search(
        rf"(?m)^MIGRATION_DATABASE_URL=postgresql\+asyncpg://{MIGRATOR_ROLE}:", migration
    )
    assert APP_ROLE not in re.sub(r"(?m)^#.*$", "", migration)
    assert re.search(r"(?m)^POSTGRES_PASSWORD=", _text(ROOT / ".env.postgres.example"))


def test_real_env_files_are_ignored():
    ignored = _text(ROOT / ".gitignore").splitlines()
    for name in (".env.production", ".env.migration", ".env.postgres"):
        assert name in ignored, f"{name} could be committed"


def test_dev_compose_already_separates_the_roles():
    services = _compose("docker-compose.yml")
    assert f"//{MIGRATOR_ROLE}:" in str(services["migrate"]["environment"])
    for name in ("backend", "temporal-worker"):
        env = str(services[name]["environment"])
        assert (
            f"//{APP_ROLE}:" in env
            and f"SYSTEM_DATABASE_URL=postgresql+asyncpg://{SYSTEM_ROLE}:" in env
        )
        assert "MIGRATION_DATABASE_URL" not in env
        assert (
            services[name]["depends_on"]["migrate"]["condition"] == "service_completed_successfully"
        )
    mounts = services["postgres"]["volumes"]
    assert any(m.startswith("./deploy/postgres:") for m in mounts), (
        "the dev bootstrap includes the canonical script"
    )


# --- SQL bootstrap ---------------------------------------------------------------------


def test_the_bootstrap_scripts_hold_no_passwords_and_no_unbounded_reassign():
    for name in ("provision-roles.sql", "remediate-ownership.sql"):
        sql = _without_comments(_text(ROOT / "deploy" / "postgres" / name))
        assert not re.search(r"(?i)password\s+'", sql), f"{name} hard-codes a password"
        assert "REASSIGN OWNED" not in sql.upper(), f"{name} sweeps up every object a role owns"
        assert "DROP OWNED" not in sql.upper()
    provision = _without_comments(_text(ROOT / "deploy" / "postgres" / "provision-roles.sql"))
    for attribute in ("NOSUPERUSER", "NOCREATEDB", "NOCREATEROLE", "NOREPLICATION"):
        assert attribute in provision
    assert not re.search(r"(?i)GRANT\s+%I\s+TO", provision), (
        "a role must not be granted another role"
    )


def test_the_dev_bootstrap_delegates_to_the_canonical_script():
    sql = _text(ROOT / "docker" / "postgres-init" / "01-init-roles.sql")
    assert "\\i /opt/nexus-postgres/provision-roles.sql" in sql
    assert "\r" not in sql, "psql meta-commands need LF endings"
    assert "eol=lf" in _text(ROOT / ".gitattributes")


# --- the entry point and the runtime guard ---------------------------------------------


def test_the_runtime_refuses_to_start_with_the_migrator_credential(monkeypatch):
    monkeypatch.delenv("MIGRATION_DATABASE_URL", raising=False)
    enforce_no_migration_credential()
    secret = "postgresql+asyncpg://nexus_migrator:sup3rsecret@db/nexus"
    monkeypatch.setenv("MIGRATION_DATABASE_URL", secret)
    with pytest.raises(ConfigurationError) as raised:
        enforce_no_migration_credential()
    assert raised.value.code == "MIGRATION_CREDENTIAL_IN_RUNTIME"
    assert "sup3rsecret" not in str(raised.value) and "nexus_migrator" not in str(raised.value)


async def test_migration_never_falls_back_to_the_application_url():
    app_url = "postgresql+asyncpg://nexus_app:apppw@db/nexus"
    with pytest.raises(db_migrate.PreflightError, match="MIGRATION_DATABASE_URL is not set"):
        await db_migrate.run({"DATABASE_URL": app_url, "SYSTEM_DATABASE_URL": app_url})
    with pytest.raises(db_migrate.PreflightError, match="MIGRATION_DATABASE_URL is not set"):
        await db_migrate.run({"DATABASE_URL": app_url, "MIGRATION_DATABASE_URL": "  "})


@pytest.mark.parametrize(
    "url", ["sqlite+aiosqlite:///x.db", "postgresql://u:hunter2@h/db", "not a url:hunter2"]
)
async def test_a_bad_migration_url_is_refused_without_echoing_it(url):
    with pytest.raises(db_migrate.PreflightError) as raised:
        await db_migrate.run({"MIGRATION_DATABASE_URL": url})
    assert "hunter2" not in str(raised.value)


async def test_the_three_roles_must_differ_before_any_connection_is_made():
    problems = await db_migrate.check_roles(
        "postgresql+asyncpg://unreachable.invalid/db", "r", "r", "s"
    )
    assert problems and "three different roles" in problems[0]
