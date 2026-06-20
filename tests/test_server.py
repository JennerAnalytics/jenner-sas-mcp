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


def _csv_response(text, content_type="text/csv; charset=utf-8"):
    req = httpx.Request("GET", "https://example/v1/run/r/datasets/a")
    return httpx.Response(
        200, headers={"content-type": content_type}, text=text, request=req
    )


def test_parse_dataset_preview_csv():
    # The 1-row Avro dataset that used to come back empty (resp.json() raised
    # JSONDecodeError on the CSV body).
    out = server._parse_dataset_preview(_csv_response("x\n1\n"))
    assert out == {
        "columns": ["x"],
        "rows": [{"x": "1"}],
        "row_count": 1,
        "format": "csv",
    }


def test_parse_dataset_preview_quoted_comma():
    out = server._parse_dataset_preview(_csv_response('name,id\n"Smith, John",1\nDoe,2\n'))
    assert out["columns"] == ["name", "id"]
    assert out["rows"][0] == {"name": "Smith, John", "id": "1"}
    assert out["row_count"] == 2


def test_parse_dataset_preview_header_only_and_empty():
    header_only = server._parse_dataset_preview(_csv_response("x\n"))
    assert header_only == {"columns": ["x"], "rows": [], "row_count": 0, "format": "csv"}

    empty = server._parse_dataset_preview(_csv_response(""))
    assert empty == {"columns": [], "rows": [], "row_count": 0, "format": "csv"}


def test_parse_dataset_preview_passes_through_json():
    # Future-proof: if the API ever serves JSON, return it untouched.
    resp = _csv_response('{"columns": ["x"], "rows": [{"x": 1}]}', content_type="application/json")
    out = server._parse_dataset_preview(resp)
    assert out == {"columns": ["x"], "rows": [{"x": 1}]}


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


class _CsvStubClient:
    """Async-context client whose GET returns a real httpx.Response (CSV)."""

    def __init__(self, text, capture):
        self._text = text
        self._capture = capture

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def get(self, url, **kwargs):
        self._capture["url"] = url
        self._capture.update(kwargs)
        req = httpx.Request("GET", url)
        return httpx.Response(
            200, headers={"content-type": "text/csv; charset=utf-8"},
            text=self._text, request=req,
        )


@pytest.mark.asyncio
async def test_dataset_preview_parses_csv_body(monkeypatch):
    # Regression: the API serves previews as CSV; the tool must not call
    # resp.json() (which raised and surfaced as an empty/failed preview).
    monkeypatch.delenv("JENNER_API_KEY", raising=False)
    capture: dict = {}
    factory = lambda *a, **k: _CsvStubClient("x\n1\n", capture)  # noqa: E731
    with mock.patch.object(server.httpx, "AsyncClient", factory):
        out = await server.dataset_preview("r_1", "a", "tok")
    assert out == {"columns": ["x"], "rows": [{"x": "1"}], "row_count": 1, "format": "csv"}
    assert "error" not in out
    assert capture["url"].endswith("/v1/run/r_1/datasets/a")
    assert capture["params"]["token"] == "tok"


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
