import pytest
from fastapi.testclient import TestClient


@pytest.fixture(autouse=True)
def studio_env(tmp_path, monkeypatch):
    monkeypatch.setenv("STUDIO_DATA", str(tmp_path))
    monkeypatch.setenv("STUDIO_DB", str(tmp_path / "studio.db"))
    return tmp_path


@pytest.fixture
def client():
    from studio.main import app

    return TestClient(app)
