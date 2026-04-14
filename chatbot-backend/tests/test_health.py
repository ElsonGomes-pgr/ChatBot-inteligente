"""Testes do endpoint /health."""


async def test_health_returns_ok(client):
    response = await client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] in ("ok", "degraded")
    assert "database" in data
    assert "redis" in data
    assert "n8n" in data
    assert data["version"] == "1.0.0"


async def test_health_includes_n8n_status(client):
    """Health check deve incluir status do n8n."""
    response = await client.get("/health")
    data = response.json()
    # n8n_callback_url vazio nos testes → "not_configured"
    assert data["n8n"] in ("ok", "degraded", "unreachable", "not_configured")
