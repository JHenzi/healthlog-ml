"""Privacy guards (risks.md E1, E2): nothing personal in git, no hidden network calls."""

from __future__ import annotations

import ipaddress
import re
import shutil
import socket
import subprocess

import pytest
import yaml

from tests.conftest import COMPANION_DIR, REPO_DIR

MAX_JSON_BYTES = 1_000_000
FORBIDDEN_FILES = re.compile(r"(^|/)(HealthAutoExport[^/]*|[^/]*\.dump|[^/]*\.sql\.gz|[^/]*\.json\.(gz|zst)|\.env)$")


@pytest.mark.skipif(shutil.which("git") is None, reason="git not available")
def test_repo_holds_no_exports_dumps_or_env_files():
    files = subprocess.run(["git", "ls-files"], cwd=REPO_DIR, capture_output=True, text=True, check=True).stdout.split()
    assert [f for f in files if FORBIDDEN_FILES.search(f)] == []
    big_json = [f for f in files if f.endswith(".json") and (REPO_DIR / f).stat().st_size > MAX_JSON_BYTES]
    assert big_json == []


def test_app_code_has_no_http_clients():
    """R5: the Companion never fetches. Weather comes from the separate collector container (collector/), which
    is tested in tests/unit/test_collector.py."""
    pattern = re.compile(r"^\s*(import|from)\s+(httpx|requests|urllib\.request|urllib3|aiohttp|http\.client)\b", re.M)
    offenders = [p.name for p in (COMPANION_DIR / "app").rglob("*.py") if pattern.search(p.read_text())]
    assert offenders == []


def _compose_files() -> tuple[dict, dict]:
    class Loader(yaml.SafeLoader):
        pass

    Loader.add_constructor("!reset", lambda _loader, _node: [])
    local = yaml.load((REPO_DIR / "compose.local.yml").read_text(), Loader=Loader)
    companion = yaml.load((REPO_DIR / "compose.companion.yml").read_text(), Loader=Loader)
    return local, companion


def test_services_with_health_data_have_no_route_out():
    """R5 at the network level. deploy.sh proves it on the running stack with scripts/check_egress.sh."""
    local, companion = _compose_files()
    assert local["networks"]["private"]["internal"] is True
    services = {**local["services"], **companion["services"]}
    for name in ("healthlog-db", "healthlog", "grafana", "companion-web", "companion-jobs"):
        assert services[name]["networks"] == ["private"], name
        assert not services[name].get("ports"), name


def test_only_the_edge_containers_publish_ports():
    local, companion = _compose_files()
    publishing = {n for n, s in {**local["services"], **companion["services"]}.items() if s.get("ports")}
    assert publishing == {"healthlog-edge", "grafana-edge", "companion-edge"}


def test_outbound_containers_cannot_reach_the_database():
    _, companion = _compose_files()
    for name in ("companion-collector", "companion-courier"):
        assert companion["services"][name]["networks"] == ["outside"], name


@pytest.fixture
def block_egress(monkeypatch):
    """Fail any Python-level connection to a non-loopback address."""
    attempts: list[str] = []
    real_connect = socket.socket.connect

    def guarded(self, address):
        host = address[0] if isinstance(address, tuple) else address
        try:
            loopback = ipaddress.ip_address(host).is_loopback
        except ValueError:
            loopback = host in ("localhost", "testserver")
        if not loopback:
            attempts.append(str(host))
            raise OSError(f"egress blocked in tests: {host}")
        return real_connect(self, address)

    monkeypatch.setattr(socket.socket, "connect", guarded)
    return attempts


def test_pages_and_jobs_work_offline(client, db, block_egress):
    from app import auth, upstream

    auth.set_password(db, "offline password 123")
    page = client.get("/login")
    csrf = re.search(r'name="csrf" value="([^"]+)"', page.text).group(1)
    client.post("/login", data={"password": "offline password 123", "csrf": csrf})
    assert client.get("/").status_code == 200
    upstream.check_upstream(db)
    assert block_egress == []
