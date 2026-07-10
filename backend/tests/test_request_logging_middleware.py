"""Тесты middleware наблюдаемости: X-Request-ID и редакция секретов в access-log."""

import logging

from fastapi.testclient import TestClient


def test_request_id_present(client: TestClient) -> None:
    headers = {k.lower(): v for k, v in client.get("/health").headers.items()}
    assert "x-request-id" in headers
    assert headers["x-request-id"]


def test_incoming_request_id_preserved(client: TestClient) -> None:
    r = client.get("/health", headers={"X-Request-ID": "trace-abc-123"})
    assert r.headers.get("X-Request-ID") == "trace-abc-123"


def test_response_has_header_on_ui(client: TestClient) -> None:
    r = client.get("/ui/login")
    assert r.headers.get("X-Request-ID")


def _access_log(caplog) -> str:  # noqa: ANN001
    return " ".join(r.getMessage() for r in caplog.records if r.name == "botfleet.access")


def test_access_log_redacts_token(client: TestClient, caplog) -> None:  # noqa: ANN001
    with caplog.at_level(logging.INFO, logger="botfleet.access"):
        client.get("/health?access_token=SECRETTOKEN123&x=1")
    logged = _access_log(caplog)
    assert "access" in logged
    assert "SECRETTOKEN123" not in logged  # секрет замазан в access-log именно botfleet


def test_access_log_has_request_metadata(client: TestClient, caplog) -> None:  # noqa: ANN001
    with caplog.at_level(logging.INFO, logger="botfleet.access"):
        client.get("/health")
    logged = _access_log(caplog)
    assert "method=GET" in logged
    assert "status=200" in logged
    assert "request_id=" in logged
