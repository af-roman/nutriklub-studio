import base64


def test_healthz_is_open(client):
    response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json()["ok"] is True


def test_basic_auth_protects_app_when_configured(client, monkeypatch):
    monkeypatch.setenv("STUDIO_USER", "manager")
    monkeypatch.setenv("STUDIO_PASSWORD", "secret")
    denied = client.get("/")
    assert denied.status_code == 401
    assert denied.headers.get("www-authenticate", "").startswith("Basic")

    token = base64.b64encode(b"manager:secret").decode("ascii")
    allowed = client.get("/", headers={"Authorization": f"Basic {token}"})
    assert allowed.status_code == 200

    health = client.get("/healthz")
    assert health.status_code == 200


def test_without_credentials_app_stays_open(client, monkeypatch):
    monkeypatch.delenv("STUDIO_USER", raising=False)
    monkeypatch.delenv("STUDIO_PASSWORD", raising=False)
    response = client.get("/")
    assert response.status_code == 200
