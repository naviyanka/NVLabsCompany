"""The Compose dashboard talks to the real backend, not the dev server's mock API."""

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]


def test_compose_dashboard_proxies_to_the_backend():
    services = yaml.safe_load((ROOT / "docker-compose.yml").read_text())["services"]
    env = services["frontend"]["environment"]
    assert "PROXY_API=true" in env  # dashboard/server.ts serves mock data otherwise
    assert "NEXUS_API_URL=http://backend:8000" in env
