"""
Testes de segurança:
- Rate limiting
- Validação de assinatura Meta/Messenger
- Autenticação nos diferentes endpoints
"""

import hmac
import hashlib
import pytest
from unittest.mock import patch


# ── Meta Messenger HMAC ────────────────────────────────────────────────────

class TestMetaSignature:

    def test_valid_signature(self, test_settings):
        with patch("app.core.security.settings", test_settings):
            from app.core.security import verify_meta_signature

            payload = b'{"entry":[{"messaging":[{"sender":{"id":"123"}}]}]}'
            sig = "sha256=" + hmac.new(
                test_settings.meta_app_secret.encode(),
                payload,
                hashlib.sha256,
            ).hexdigest()

            assert verify_meta_signature(payload, sig) is True

    def test_invalid_signature(self, test_settings):
        with patch("app.core.security.settings", test_settings):
            from app.core.security import verify_meta_signature
            payload = b'{"entry":[]}'
            assert verify_meta_signature(payload, "sha256=fake") is False

    def test_missing_signature(self, test_settings):
        with patch("app.core.security.settings", test_settings):
            from app.core.security import verify_meta_signature
            payload = b'{"entry":[]}'
            assert verify_meta_signature(payload, "") is False

    def test_no_sha256_prefix(self, test_settings):
        with patch("app.core.security.settings", test_settings):
            from app.core.security import verify_meta_signature
            payload = b'{"entry":[]}'
            assert verify_meta_signature(payload, "md5=abc123") is False


# ── Autenticação por endpoint ──────────────────────────────────────────────

async def test_messages_requires_webhook_secret(client):
    """POST /messages/incoming exige X-Webhook-Secret."""
    r = await client.post("/api/v1/messages/incoming", json={
        "external_user_id": "x", "channel": "api", "text": "test",
    })
    assert r.status_code == 422  # Header obrigatório ausente


async def test_messages_wrong_webhook_secret_returns_401(client):
    """POST /messages/incoming com secret errado retorna 401."""
    r = await client.post("/api/v1/messages/incoming", json={
        "external_user_id": "x", "channel": "api", "text": "test",
    }, headers={"X-Webhook-Secret": "wrong"})
    assert r.status_code == 401


async def test_conversations_list_requires_api_key(client):
    """GET /conversations/ exige X-API-Key."""
    r = await client.get("/api/v1/conversations/")
    assert r.status_code == 422


async def test_conversations_list_wrong_api_key_returns_401(client):
    """GET /conversations/ com key errada retorna 401."""
    r = await client.get("/api/v1/conversations/", headers={"X-API-Key": "wrong"})
    assert r.status_code == 401


async def test_conversations_detail_requires_api_key(client):
    """GET /conversations/{id} exige X-API-Key."""
    r = await client.get("/api/v1/conversations/some-id")
    assert r.status_code == 422


async def test_agent_reply_requires_api_key(client):
    """POST /conversations/{id}/reply exige X-API-Key."""
    r = await client.post("/api/v1/conversations/some-id/reply", json={
        "text": "test", "agent_id": "a1",
    })
    assert r.status_code == 422


async def test_cleanup_requires_webhook_secret(client):
    """POST /conversations/cleanup exige X-Webhook-Secret."""
    r = await client.post("/api/v1/conversations/cleanup")
    assert r.status_code == 422


async def test_close_requires_api_key(client):
    """POST /conversations/{id}/close exige X-API-Key."""
    r = await client.post("/api/v1/conversations/some-id/close")
    assert r.status_code == 422


async def test_handoff_requires_webhook_secret(client):
    """POST /conversations/{id}/handoff exige X-Webhook-Secret."""
    r = await client.post("/api/v1/conversations/some-id/handoff")
    assert r.status_code == 422
