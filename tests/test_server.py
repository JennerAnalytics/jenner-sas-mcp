"""Unit tests for the Jenner SAS MCP server.

No network: the pure reshaping/clipping helpers are tested directly, and
the HTTP tools are exercised against a stubbed ``httpx.AsyncClient``.
"""

from __future__ import annotations

import contextlib
from unittest import mock

import httpx
import pytest

from jenner_sas_mcp import server


# --- pure helpers ---------------------------------------------------------


def test_clip_short_text_unchanged(monkeypatch):
    monkeypatch.setenv("JENNER_MAX_LOG_CHARS", "1000")
    assert server._clip("hello") == "hello"
    assert server._clip(None) is None


def test_clip_keeps_head_and_tail(monkeypatch):
    monkeypatch.setenv("JENNER_MAX_LOG_CHARS", "100")
    text = "A" * 60 + "B" * 60  # 120 > 100
    clipped = server._clip(text)
    assert clipped.startswith("A")
    assert clipped.rstrip().endswith("B")
    assert "characters omitted" in clipped
    assert len(clipped) < len(text) + 200


def test_auth_headers(monkeypatch):
    monkeypatch.delenv("JENNER_API_KEY", raising=False)
    assert server._auth_headers() == {}
    monkeypatch.setenv("JENNER_API_KEY", "secret")
    assert server._auth_headers() == {"Authorization": "Bearer secret"}


def test_summarize_run_shape():
    raw = {
        "run_id": "r_abc",
        "status": "ok",
        "exit_code": 1,  # warnings, still ok
        "jenner_version": "1.5.0",
        "duration_ms": 12,
        "log": "NOTE: done",
        "output": "listing",
        "datasets": [
            {
                "name": "final",
                "rows": 3,
                "columns": ["id", "x"],
                "file_format": "avro",
                "preview_url": "/p",
                "download_url": "/d",
            }
        ],
        "files": [
            {"name": "p.png", "content_type": "image/png", "size_bytes": 9, "url": "/f"}
        ],
        "diagnostics": {"parse_warnings": [], "runtime_warnings": []},
        "access_token": "tok",
    }
    s = server._summarize_run(raw)
    assert s["ok"] is True  # exit_code 1 < 2
    assert s["run_id"] == "r_abc"
    assert s["datasets"][0]["rows"] == 3
    assert s["files"][0]["name"] == "p.png"
    assert s["access_token"] == "tok"


def test_summarize_run_error_severity():
    s = server._summarize_run({"exit_code": 2})
    assert s["ok"] is False


def test_error_classification():
    req = httpx.Request("POST", "https://example/v1/run")
    resp = httpx.Response(403, text="forbidden", request=req)
    out = server._error(httpx.HTTPStatusError("x", request=req, response=resp))
    assert out["error"] == "http_error"
    assert out["status_code"] == 403

    out2 = server._error(httpx.TimeoutException("slow"))
    assert out2["error"] == "timeout"

    out3 = server._error(RuntimeError("boom"))
    assert out3["error"] == "request_failed"


# --- HTTP tools against a stubbed client ----------------------------------


class _StubResponse:
    def __init__(self, payload):
        self._payload = payload

    def json(self):
        return self._payload

    def raise_for_status(self):
        return None


class _StubClient:
    """Minimal async-context-manager stand-in for httpx.AsyncClient."""

    def __init__(self, payload, capture):
        self._payload = payload
        self._capture = capture

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def post(self, url, **kwargs):
        self._capture["method"] = "POST"
        self._capture["url"] = url
        self._capture.update(kwargs)
        return _StubResponse(self._payload)

    async def get(self, url, **kwargs):
        self._capture["method"] = "GET"
        self._capture["url"] = url
        self._capture.update(kwargs)
        return _StubResponse(self._payload)


@contextlib.contextmanager
def _stub_httpx(payload):
    capture: dict = {}
    factory = lambda *a, **k: _StubClient(payload, capture)  # noqa: E731
    with mock.patch.object(server.httpx, "AsyncClient", factory):
        yield capture


@pytest.mark.asyncio
async def test_run_sas_sends_multipart_and_summarizes(monkeypatch):
    monkeypatch.delenv("JENNER_API_KEY", raising=False)
    payload = {"run_id": "r_1", "status": "ok", "exit_code": 0, "log": "ok"}
    with _stub_httpx(payload) as cap:
        out = await server.run_sas("data _null_; run;", deterministic=True, timeout=30)
    assert out["run_id"] == "r_1"
    assert out["ok"] is True
    assert cap["url"].endswith("/v1/run")
    assert cap["data"]["deterministic"] == "true"
    assert cap["data"]["timeout"] == "30"
    assert "script" in cap["files"]


@pytest.mark.asyncio
async def test_run_sas_deterministic_false(monkeypatch):
    monkeypatch.delenv("JENNER_API_KEY", raising=False)
    with _stub_httpx({"run_id": "r", "exit_code": 0}) as cap:
        await server.run_sas("x", deterministic=False)
    assert cap["data"]["deterministic"] == "false"


@pytest.mark.asyncio
async def test_run_sas_sends_bearer_when_key_set(monkeypatch):
    monkeypatch.setenv("JENNER_API_KEY", "k")
    with _stub_httpx({"exit_code": 0}) as cap:
        await server.run_sas("x")
    assert cap["headers"]["Authorization"] == "Bearer k"


@pytest.mark.asyncio
async def test_validate_sas(monkeypatch):
    payload = {"valid": False, "diagnostics": [{"severity": "error", "message": "bad"}]}
    with _stub_httpx(payload) as cap:
        out = await server.validate_sas("proc nope;")
    assert out["valid"] is False
    assert cap["url"].endswith("/v1/validate")


@pytest.mark.asyncio
async def test_get_run_returns_unclipped(monkeypatch):
    monkeypatch.setenv("JENNER_MAX_LOG_CHARS", "10")
    big = "L" * 5000
    with _stub_httpx({"run_id": "r", "exit_code": 0, "log": big, "output": "o"}) as cap:
        out = await server.get_run("r", "tok")
    assert out["log"] == big  # not clipped on explicit retrieval
    assert cap["params"]["token"] == "tok"


@pytest.mark.asyncio
async def test_dataset_preview(monkeypatch):
    monkeypatch.delenv("JENNER_API_KEY", raising=False)
    payload = {"rows": 2, "columns": ["id", "x"], "data": [{"id": 1, "x": 9}]}
    with _stub_httpx(payload) as cap:
        out = await server.dataset_preview("r_42", "my dataset", "tok")
    assert out["rows"] == 2
    assert cap["url"].endswith("/v1/run/r_42/datasets/my%20dataset")
    assert cap["params"]["token"] == "tok"


@pytest.mark.asyncio
async def test_get_run_url_encodes_run_id(monkeypatch):
    monkeypatch.delenv("JENNER_API_KEY", raising=False)
    with _stub_httpx({"run_id": "r/1", "exit_code": 0, "log": "", "output": ""}) as cap:
        await server.get_run("r/1", "tok")
    assert "/r%2F1" in cap["url"]


@pytest.mark.asyncio
async def test_api_url_override(monkeypatch):
    monkeypatch.setenv("JENNER_API_URL", "http://localhost:3000/")
    with _stub_httpx({"exit_code": 0}) as cap:
        await server.run_sas("x")
    assert cap["url"] == "http://localhost:3000/v1/run"
