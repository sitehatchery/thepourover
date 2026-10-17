import logging

import pytest
from fastapi.testclient import TestClient

from app.main import app


def test_request_log_has_the_route_template_not_the_query(client, auth, caplog):
    with caplog.at_level(logging.INFO, logger="cdp.request"):
        response = client.get("/app/profiles/search?q=julia.evans230@gmail.com", headers=auth)

    lines = [r.getMessage() for r in caplog.records if r.name == "cdp.request"]
    assert lines and lines[-1].startswith("GET /app/profiles/search 200 ")
    assert all("julia" not in line and "@" not in line for line in lines)
    assert lines[-1].endswith(f"rid={response.headers['x-request-id']}")


def test_path_parameters_are_logged_as_placeholders(client, auth, caplog):
    with caplog.at_level(logging.INFO, logger="cdp.request"):
        client.get("/app/profiles/s_999999", headers=auth)
        client.get("/nothing/jane@example.com")

    lines = [r.getMessage() for r in caplog.records if r.name == "cdp.request"]
    assert any(line.startswith("GET /app/profiles/{profile_id} 404") for line in lines)
    assert any(line.startswith("GET (no route) 404") for line in lines)
    assert not any("jane@" in line for line in lines)


def test_request_id_is_echoed_when_valid(client):
    assert client.get("/app/health", headers={"X-Request-ID": "abc-12345678"}).headers["x-request-id"] == "abc-12345678"
    generated = client.get("/app/health", headers={"X-Request-ID": "bad id\nwith newline"}).headers["x-request-id"]
    assert len(generated) == 32 and "bad" not in generated


@pytest.fixture
def broken_route():
    @app.get("/app/test-broken")
    def broken():
        message = "UNIQUE constraint failed: subscribers.email [parameters: ('jane@example.com',)]"
        raise RuntimeError(message)

    yield
    app.router.routes[:] = [r for r in app.router.routes if getattr(r, "path", "") != "/app/test-broken"]


def test_unhandled_errors_return_a_reference_and_log_no_data(settings, broken_route, caplog):
    with TestClient(app, raise_server_exceptions=False) as client, caplog.at_level(logging.ERROR, logger="cdp.error"):
        response = client.get("/app/test-broken")

    assert response.status_code == 500
    body = response.json()
    assert body["request_id"] == response.headers["x-request-id"] and body["request_id"] in body["detail"]
    logged = "\n".join(r.getMessage() for r in caplog.records)
    assert "unhandled RuntimeError on GET /app/test-broken" in logged
    assert "jane@example.com" not in logged and "jane@example.com" not in response.text


def test_health_checks_are_not_logged_and_admin_routes_are_templated(client, caplog):
    with caplog.at_level(logging.INFO, logger="cdp.request"):
        client.get("/app/health")
        client.get("/app/admin/subscriber/details/5", follow_redirects=False)

    lines = [r.getMessage() for r in caplog.records if r.name == "cdp.request"]
    assert not any("/app/health" in line for line in lines)
    assert any(line.startswith("GET /app/admin/{identity}/details/{pk:path} 302") for line in lines)
