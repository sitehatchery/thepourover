from datetime import timedelta

from sqlalchemy import select

from app.models import ApiClient
from app.rules import utcnow


def test_health_needs_no_auth(client):
    response = client.get("/app/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "database": "ok", "today": "2026-09-28"}


def test_import_requires_an_api_key(client):
    assert client.post("/app/import").status_code == 401
    assert client.post("/app/import", headers={"Authorization": "Bearer cdp_wrong"}).status_code == 401


def test_import_with_api_key(client, api_key):
    headers = {"Authorization": f"Bearer {api_key}"}

    response = client.post("/app/import", headers=headers)
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "succeeded"
    assert body["has_error_report"] is True

    runs = client.get("/app/import/runs", headers=headers).json()
    assert runs[0]["import_run_id"] == body["import_run_id"]

    report = client.get("/app/import/report", headers=headers)
    assert report.status_code == 200
    assert report.text.startswith("severity,file,row,field,value,reason")


def test_import_source_lists_files_without_server_paths(client, auth):
    body = client.get("/app/import/source", headers=auth).json()

    assert body["kind"] == "local" and body["available"] is True
    assert body["folder"] == "data/sample/"
    assert sorted(f["name"] for f in body["files"]) == ["app_users.csv", "subscribers.csv", "web_events.csv"]
    assert "\\" not in str(body) and ":" not in body["folder"]  # a project path, never the server path


def test_revoked_and_expired_keys_are_rejected(client, session, api_key):
    headers = {"Authorization": f"Bearer {api_key}"}
    key = session.scalar(select(ApiClient))

    key.expires_at = utcnow() - timedelta(minutes=1)
    session.commit()
    assert client.get("/app/import/runs", headers=headers).status_code == 401

    key.expires_at = None
    key.revoked_at = utcnow()
    session.commit()
    assert client.get("/app/import/runs", headers=headers).status_code == 401
