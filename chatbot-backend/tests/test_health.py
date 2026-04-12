"""Testes do endpoint /health."""


async def test_health_returns_ok(client):
    response = await client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] in ("ok", "degraded")
    assert "database" in data
    assert "redis" in data
    assert data["version"] == "1.0.0"
