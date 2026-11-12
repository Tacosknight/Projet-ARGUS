"""Vérifie que l'identité visuelle est disponible dans l'interface."""
from fastapi.testclient import TestClient

from web.app import app


def test_brand_assets_are_served():
    client = TestClient(app)
    page = client.get("/")
    assert page.status_code == 200
    assert 'src="/static/logo.png"' in page.text
    assert 'href="/static/argus.ico"' in page.text
    for path, content_type in (("/static/logo.png", "image/png"), ("/static/argus.ico", "image/vnd.microsoft.icon")):
        response = client.get(path)
        assert response.status_code == 200
        assert response.headers["content-type"] in (content_type, "image/x-icon")
        assert response.content
