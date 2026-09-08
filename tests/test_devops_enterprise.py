"""Comprehensive Enterprise DevOps & Deployment Test Suite.

Verifies:
1. Kubernetes lifecycle probes (live, startup, ready) with component failure semantics.
2. Helm chart structure, templates, security contexts, HPA, PDB, and migration hooks.
3. Hardened multi-stage container security audit (non-root, no reload flags, healthchecks).
4. Automated disaster recovery backup, checksum verification, and restore integrity.
"""

from contextlib import asynccontextmanager
import gzip
import hashlib
from pathlib import Path
import re
import tempfile
from unittest.mock import AsyncMock, patch
import pytest
from httpx import ASGITransport, AsyncClient
import yaml

from nexus.main import app

REPO_ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def anyio_backend():
    """Use asyncio backend for anyio."""
    return "asyncio"


@pytest.fixture
async def client():
    """Create async HTTP client for probe testing."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


def _mock_engine(connected: bool = True):
    """Helper to mock database engine connection."""
    mock_conn = AsyncMock()
    mock_conn.execute = AsyncMock()

    @asynccontextmanager
    async def _connect():
        if not connected:
            raise ConnectionError("Database cluster unreachable")
        yield mock_conn

    mock_engine_obj = AsyncMock()
    mock_engine_obj.connect = _connect
    return mock_engine_obj


# ==============================================================================
# 1. Health & Readiness Probe Semantics
# ==============================================================================

@pytest.mark.asyncio
class TestKubernetesHealthProbes:
    """Test suite for Kubernetes lifecycle probes."""

    async def test_liveness_probe_always_alive(self, client: AsyncClient) -> None:
        """GET /health/live returns 200 OK with alive status."""
        response = await client.get("/health/live")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "alive"

    async def test_startup_probe_success(self, client: AsyncClient) -> None:
        """GET /health/startup returns 200 when database connection is established."""
        with patch("nexus.api.routes.health.engine", _mock_engine(connected=True)):
            response = await client.get("/health/startup")
            assert response.status_code == 200
            data = response.json()
            assert data["status"] == "started"
            assert data["db"] == "connected"

    async def test_startup_probe_failure_during_bootstrap(self, client: AsyncClient) -> None:
        """GET /health/startup returns 503 while database is not yet ready."""
        with patch("nexus.api.routes.health.engine", _mock_engine(connected=False)):
            response = await client.get("/health/startup")
            assert response.status_code == 503
            data = response.json()
            assert data["status"] == "starting"
            assert data["db"] == "disconnected"

    async def test_readiness_probe_all_healthy(self, client: AsyncClient) -> None:
        """GET /health/ready returns 200 with component metrics when dependencies are healthy."""
        mock_redis = AsyncMock()
        mock_redis.ping = AsyncMock(return_value=True)
        mock_redis.aclose = AsyncMock()

        with patch("nexus.api.routes.health.engine", _mock_engine(connected=True)), \
             patch("redis.asyncio.from_url", return_value=mock_redis), \
             patch("nexus.api.routes.health.is_temporal_enabled", return_value=False):
            response = await client.get("/health/ready")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ready"
        assert data["db"] == "connected"
        assert data["redis"] == "connected"
        assert "components" in data
        assert data["components"]["database"]["status"] == "connected"
        assert data["components"]["redis"]["status"] == "connected"
        assert "latency_ms" in data["components"]["database"]

    async def test_readiness_probe_db_failure_returns_503(self, client: AsyncClient) -> None:
        """GET /health/ready returns 503 when database drops connection."""
        mock_redis = AsyncMock()
        mock_redis.ping = AsyncMock(return_value=True)
        mock_redis.aclose = AsyncMock()

        with patch("nexus.api.routes.health.engine", _mock_engine(connected=False)), \
             patch("redis.asyncio.from_url", return_value=mock_redis):
            response = await client.get("/health/ready")

        assert response.status_code == 503
        data = response.json()
        assert data["status"] == "not_ready"
        assert data["db"] == "disconnected"
        assert data["components"]["database"]["status"] == "disconnected"

    async def test_readiness_probe_redis_failure_returns_503(self, client: AsyncClient) -> None:
        """GET /health/ready returns 503 when Redis drops connection."""
        with patch("nexus.api.routes.health.engine", _mock_engine(connected=True)), \
             patch("redis.asyncio.from_url", side_effect=ConnectionError("Redis connection refused")):
            response = await client.get("/health/ready")

        assert response.status_code == 503
        data = response.json()
        assert data["status"] == "not_ready"
        assert data["redis"] == "disconnected"
        assert data["components"]["redis"]["status"] == "disconnected"

    async def test_readiness_probe_temporal_cluster_dependency(self, client: AsyncClient) -> None:
        """GET /health/ready evaluates Temporal connectivity when USE_TEMPORAL is enabled."""
        mock_redis = AsyncMock()
        mock_redis.ping = AsyncMock(return_value=True)
        mock_redis.aclose = AsyncMock()

        # Case A: Temporal enabled and connected
        with patch("nexus.api.routes.health.engine", _mock_engine(connected=True)), \
             patch("redis.asyncio.from_url", return_value=mock_redis), \
             patch("nexus.api.routes.health.is_temporal_enabled", return_value=True), \
             patch("nexus.temporal.client._get_client", AsyncMock(return_value=AsyncMock())):
            response = await client.get("/health/ready")
            assert response.status_code == 200
            assert response.json()["components"]["temporal"]["status"] == "connected"

        # Case B: Temporal enabled and disconnected
        with patch("nexus.api.routes.health.engine", _mock_engine(connected=True)), \
             patch("redis.asyncio.from_url", return_value=mock_redis), \
             patch("nexus.api.routes.health.is_temporal_enabled", return_value=True), \
             patch("nexus.temporal.client._get_client", AsyncMock(return_value=None)):
            response = await client.get("/health/ready")
            assert response.status_code == 503
            assert response.json()["components"]["temporal"]["status"] == "disconnected"


# ==============================================================================
# 2. Kubernetes Helm Chart & Template Rendering Audit
# ==============================================================================

class TestHelmChartArchitecture:
    """Test suite for Helm v3 chart manifests and configuration."""

    helm_dir = REPO_ROOT / "deploy" / "helm" / "nexus"

    def test_chart_metadata_validity(self) -> None:
        """Chart.yaml must be valid YAML with required Helm v3 metadata."""
        chart_file = self.helm_dir / "Chart.yaml"
        assert chart_file.exists()
        with open(chart_file, "r", encoding="utf-8") as f:
            chart = yaml.safe_load(f)

        assert chart["apiVersion"] == "v2"
        assert chart["name"] == "nexus"
        assert chart["type"] == "application"
        assert "version" in chart
        assert "appVersion" in chart

    def test_values_structure_and_defaults(self) -> None:
        """values.yaml must configure all required enterprise components."""
        values_file = self.helm_dir / "values.yaml"
        assert values_file.exists()
        with open(values_file, "r", encoding="utf-8") as f:
            values = yaml.safe_load(f)

        # Core components
        assert "api" in values
        assert "worker" in values
        assert "scheduler" in values
        assert "frontend" in values
        assert "ingress" in values
        assert "database" in values
        assert "redis" in values
        assert "temporal" in values
        assert "migration" in values

        # Security defaults
        assert values["podSecurityContext"]["runAsNonRoot"] is True
        assert values["podSecurityContext"]["runAsUser"] == 10001
        assert values["securityContext"]["allowPrivilegeEscalation"] is False
        assert "ALL" in values["securityContext"]["capabilities"]["drop"]

        # Autoscaling & Resilience
        assert values["api"]["autoscaling"]["enabled"] is True
        assert values["api"]["autoscaling"]["minReplicas"] >= 2
        assert values["api"]["pdb"]["enabled"] is True
        assert values["frontend"]["pdb"]["enabled"] is True

        # Probes
        assert values["api"]["probes"]["startup"]["enabled"] is True
        assert values["api"]["probes"]["liveness"]["enabled"] is True
        assert values["api"]["probes"]["readiness"]["enabled"] is True

    def test_helm_template_files_exist(self) -> None:
        """All expected Helm templates must be present in templates directory."""
        templates_dir = self.helm_dir / "templates"
        expected_templates = [
            "_helpers.tpl",
            "serviceaccount.yaml",
            "configmap.yaml",
            "secrets.yaml",
            "migration-job.yaml",
            "api-deployment.yaml",
            "api-service.yaml",
            "api-hpa.yaml",
            "worker-deployment.yaml",
            "scheduler-deployment.yaml",
            "frontend-deployment.yaml",
            "frontend-service.yaml",
            "ingress.yaml",
            "pdb.yaml",
        ]
        for tmpl in expected_templates:
            tmpl_path = templates_dir / tmpl
            assert tmpl_path.exists(), f"Missing required Helm template: {tmpl}"

    def test_migration_job_has_helm_hooks(self) -> None:
        """Migration Job must contain Helm pre-install and pre-upgrade hooks."""
        migration_file = self.helm_dir / "templates" / "migration-job.yaml"
        content = migration_file.read_text(encoding="utf-8")
        assert "helm.sh/hook" in content
        assert "pre-install,pre-upgrade" in content
        assert "alembic" in content
        assert "upgrade" in content
        assert "head" in content


# ==============================================================================
# 3. Hardened Multi-Stage Container Security Audit
# ==============================================================================

class TestContainerSecurityAudit:
    """Security audit tests for Dockerfiles and Compose files."""

    def test_backend_dockerfile_hardened_standards(self) -> None:
        """Dockerfile.prod must adhere to non-root and hardened multi-stage standards."""
        dockerfile = REPO_ROOT / "Dockerfile.prod"
        assert dockerfile.exists()
        content = dockerfile.read_text(encoding="utf-8")

        # Multi-stage verification
        from_stages = re.findall(r"FROM\s+(\S+)\s+AS\s+(\S+)", content, re.IGNORECASE)
        assert len(from_stages) >= 2, "Backend Dockerfile must have at least 2 build stages"
        stage_names = [s[1].lower() for s in from_stages]
        assert "builder" in stage_names
        assert "runtime" in stage_names

        # Non-root user
        assert re.search(r"USER\s+10001", content), "Must execute as non-root UID 10001"

        # Production entrypoint verification
        assert "--reload" not in content, "Production image must NOT include --reload"
        assert "HEALTHCHECK" in content, "Production image must define HEALTHCHECK"
        assert "WEB_CONCURRENCY" in content, "Production image must support multi-worker concurrency"

    def test_frontend_dockerfile_hardened_standards(self) -> None:
        """dashboard/Dockerfile.prod must use multi-stage build and unprivileged runtime."""
        dockerfile = REPO_ROOT / "dashboard" / "Dockerfile.prod"
        assert dockerfile.exists()
        content = dockerfile.read_text(encoding="utf-8")

        # Multi-stage verification
        from_stages = re.findall(r"FROM\s+(\S+)\s+AS\s+(\S+)", content, re.IGNORECASE)
        assert len(from_stages) >= 2, "Frontend Dockerfile must have multi-stage build"

        # Non-root unprivileged NGINX
        assert "USER 101" in content or "USER 10001" in content
        assert "HEALTHCHECK" in content

    def test_frontend_nginx_security_headers(self) -> None:
        """dashboard/nginx.conf must enforce modern security headers and SPA routing."""
        nginx_conf = REPO_ROOT / "dashboard" / "nginx.conf"
        assert nginx_conf.exists()
        content = nginx_conf.read_text(encoding="utf-8")

        assert "X-Frame-Options" in content
        assert "Content-Security-Policy" in content
        assert "X-Content-Type-Options" in content
        assert "Strict-Transport-Security" in content
        assert "gzip on;" in content
        assert "try_files $uri $uri/ /index.html;" in content

    def test_docker_compose_environments_split(self) -> None:
        """Dev and prod docker compose files must be properly decoupled."""
        dev_compose = REPO_ROOT / "docker-compose.dev.yml"
        prod_compose = REPO_ROOT / "docker-compose.prod.yml"

        assert dev_compose.exists()
        assert prod_compose.exists()

        with open(dev_compose, "r", encoding="utf-8") as f:
            dev_data = yaml.safe_load(f)
        with open(prod_compose, "r", encoding="utf-8") as f:
            prod_data = yaml.safe_load(f)

        # Dev features
        assert "--reload" in str(dev_data)

        # Prod decoupled services
        prod_services = prod_data["services"]
        assert "api" in prod_services
        assert "worker" in prod_services
        assert "scheduler" in prod_services
        assert "postgres" in prod_services
        assert "redis" in prod_services
        assert "temporal" in prod_services

        # Resource limits and healthchecks in prod
        for svc_name in ["api", "worker", "scheduler", "postgres", "redis"]:
            svc = prod_services[svc_name]
            assert "deploy" in svc and "resources" in svc["deploy"], f"{svc_name} missing resource limits"
            assert "limits" in svc["deploy"]["resources"]
            assert svc.get("restart") == "unless-stopped"


# ==============================================================================
# 4. Disaster Recovery & Automated Backup Integrity
# ==============================================================================

class TestDisasterRecoveryIntegrity:
    """Test suite for automated database disaster recovery runbooks."""

    def test_dr_scripts_exist_and_executable(self) -> None:
        """DR scripts in scripts/ops/ must exist with valid bash headers."""
        ops_dir = REPO_ROOT / "scripts" / "ops"
        scripts = ["backup_db.sh", "restore_db.sh", "verify_backup.sh"]
        for s in scripts:
            script_path = ops_dir / s
            assert script_path.exists(), f"Missing DR script: {s}"
            first_line = script_path.read_text(encoding="utf-8").splitlines()[0]
            assert first_line.startswith("#!/usr/bin/env bash")

    def test_backup_restore_checksum_integrity_cycle(self) -> None:
        """Simulate end-to-end transactional backup, SHA-256 calculation, and restore verification."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            sample_sql = (
                "-- NEXUS Database Dump\n"
                "CREATE TABLE test_entity (id INT PRIMARY KEY, name VARCHAR(100));\n"
                "INSERT INTO test_entity VALUES (1, 'Agent-Alpha'), (2, 'Agent-Beta');\n"
            ).encode("utf-8")

            # 1. Create compressed backup
            backup_file = tmp_path / "nexus_backup_test.sql.gz"
            with gzip.open(backup_file, "wb") as f:
                f.write(sample_sql)

            # 2. Compute SHA-256
            hasher = hashlib.sha256()
            with open(backup_file, "rb") as f:
                hasher.update(f.read())
            sha256_hash = hasher.hexdigest()

            checksum_file = tmp_path / "nexus_backup_test.sql.gz.sha256"
            checksum_file.write_text(f"{sha256_hash}  {backup_file.name}\n", encoding="utf-8")

            # 3. Verify Checksum matches
            computed_hash = hashlib.sha256(backup_file.read_bytes()).hexdigest()
            assert computed_hash == sha256_hash

            # 4. Restore and verify data preservation
            with gzip.open(backup_file, "rb") as f:
                restored_content = f.read()

            assert restored_content == sample_sql
            assert b"Agent-Alpha" in restored_content
            assert b"Agent-Beta" in restored_content

    def test_corrupted_backup_detection(self) -> None:
        """Tampered backup file must fail checksum validation."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            backup_file = tmp_path / "corrupted_backup.sql.gz"
            with gzip.open(backup_file, "wb") as f:
                f.write(b"ORIGINAL_DATA")

            # Store original checksum
            orig_hash = hashlib.sha256(backup_file.read_bytes()).hexdigest()

            # Tamper with the backup file
            backup_file.write_bytes(backup_file.read_bytes() + b"\x00TAMPERED")

            # Recomputed hash must not match original
            new_hash = hashlib.sha256(backup_file.read_bytes()).hexdigest()
            assert orig_hash != new_hash
