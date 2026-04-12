"""
Testes dos endpoints de conversas:
- GET /api/v1/conversations/ (listagem)
- GET /api/v1/conversations/{id} (detalhe)
- POST /api/v1/conversations/{id}/reply (resposta do agente)
- POST /api/v1/conversations/{id}/close (fechar)
- POST /api/v1/conversations/cleanup (timeout)
"""

from unittest.mock import AsyncMock, patch

API_KEY_HEADERS = {"X-API-Key": "test_api_key"}
WEBHOOK_HEADERS = {"X-Webhook-Secret": "test_webhook_secret"}

SAMPLE_MESSAGE = {
    "external_user_id": "fb_test_conv",
    "channel": "messenger",
    "text": "Preciso de ajuda urgente!",
    "user_name": "João Teste",
}


async def _create_conversation(client) -> str:
    """Helper: cria uma conversa via fluxo normal."""
    with patch("app.api.routes.messages.ai_service") as mock_ai:
        mock_ai.classify_intent = AsyncMock(return_value={
            "intent": "support",
            "urgency_score": 0.3,
        })
        mock_ai.generate_response = AsyncMock(return_value=("Posso ajudar!", 100))

        r = await client.post(
            "/api/v1/messages/incoming",
            json=SAMPLE_MESSAGE,
            headers=WEBHOOK_HEADERS,
        )
    return r.json()["conversation_id"]


async def _create_handoff_conversation(client) -> str:
    """Helper: cria uma conversa já em modo humano."""
    with patch("app.api.routes.messages.ai_service") as mock_ai, \
         patch("app.api.routes.messages.slack_service") as mock_slack:
        mock_ai.classify_intent = AsyncMock(return_value={
            "intent": "urgency",
            "urgency_score": 0.95,
        })
        mock_ai.generate_response = AsyncMock(return_value=("Especialista a caminho", 100))
        mock_slack.notify_handoff = AsyncMock(return_value=True)

        r = await client.post(
            "/api/v1/messages/incoming",
            json={**SAMPLE_MESSAGE, "text": "VOU CANCELAR!"},
            headers=WEBHOOK_HEADERS,
        )
    return r.json()["conversation_id"]


# ── Listagem ───────────────────────────────────────────────────────────────

async def test_list_conversations_empty(client):
    response = await client.get("/api/v1/conversations/", headers=API_KEY_HEADERS)
    assert response.status_code == 200
    assert response.json() == []


async def test_list_conversations_returns_created(client):
    conv_id = await _create_conversation(client)

    response = await client.get("/api/v1/conversations/", headers=API_KEY_HEADERS)
    assert response.status_code == 200
    data = response.json()
    assert len(data) >= 1
    assert any(c["id"] == conv_id for c in data)


async def test_list_conversations_filter_by_status(client):
    conv_id = await _create_conversation(client)

    # Filtra por active — deve encontrar
    r = await client.get("/api/v1/conversations/?status=active", headers=API_KEY_HEADERS)
    assert r.status_code == 200
    assert any(c["id"] == conv_id for c in r.json())

    # Filtra por closed — não deve encontrar
    r2 = await client.get("/api/v1/conversations/?status=closed", headers=API_KEY_HEADERS)
    assert r2.status_code == 200
    assert not any(c["id"] == conv_id for c in r2.json())


# ── Detalhe ────────────────────────────────────────────────────────────────

async def test_get_conversation_detail(client):
    conv_id = await _create_conversation(client)

    response = await client.get(
        f"/api/v1/conversations/{conv_id}",
        headers=API_KEY_HEADERS,
    )
    assert response.status_code == 200
    data = response.json()
    assert data["id"] == conv_id
    assert data["channel"] == "messenger"
    assert len(data["messages"]) >= 2  # user + bot


async def test_get_conversation_not_found(client):
    response = await client.get(
        "/api/v1/conversations/00000000-0000-0000-0000-000000000000",
        headers=API_KEY_HEADERS,
    )
    assert response.status_code == 404


# ── Resposta do agente ─────────────────────────────────────────────────────

async def test_agent_reply_saves_message(client):
    conv_id = await _create_handoff_conversation(client)

    with patch("app.api.routes.conversations.n8n_callback") as mock_n8n:
        mock_n8n.notify_agent_reply = AsyncMock(return_value=True)

        response = await client.post(
            f"/api/v1/conversations/{conv_id}/reply",
            json={"text": "Olá João, vou resolver.", "agent_id": "U_AGENT_01"},
            headers=API_KEY_HEADERS,
        )

    assert response.status_code == 200
    data = response.json()
    assert data["ok"] is True
    assert data["conversation_id"] == conv_id
    assert "message_id" in data

    # Verifica que a mensagem do agente aparece no histórico
    detail = await client.get(
        f"/api/v1/conversations/{conv_id}",
        headers=API_KEY_HEADERS,
    )
    messages = detail.json()["messages"]
    agent_msgs = [m for m in messages if m["role"] == "agent"]
    assert len(agent_msgs) == 1
    assert agent_msgs[0]["content"] == "Olá João, vou resolver."


async def test_agent_reply_fails_if_not_human_mode(client):
    conv_id = await _create_conversation(client)

    response = await client.post(
        f"/api/v1/conversations/{conv_id}/reply",
        json={"text": "Tentando responder", "agent_id": "U_AGENT_01"},
        headers=API_KEY_HEADERS,
    )
    assert response.status_code == 400
    assert "modo humano" in response.json()["detail"]


async def test_agent_reply_not_found(client):
    response = await client.post(
        "/api/v1/conversations/00000000-0000-0000-0000-000000000000/reply",
        json={"text": "Oi", "agent_id": "U_AGENT_01"},
        headers=API_KEY_HEADERS,
    )
    assert response.status_code == 404


async def test_agent_reply_empty_text_rejected(client):
    """Resposta vazia do agente deve ser rejeitada pela validação."""
    conv_id = await _create_handoff_conversation(client)
    response = await client.post(
        f"/api/v1/conversations/{conv_id}/reply",
        json={"text": "", "agent_id": "U_AGENT_01"},
        headers=API_KEY_HEADERS,
    )
    assert response.status_code == 422


# ── Close ──────────────────────────────────────────────────────────────────

async def test_close_conversation(client):
    conv_id = await _create_conversation(client)

    response = await client.post(
        f"/api/v1/conversations/{conv_id}/close",
        headers=API_KEY_HEADERS,
    )
    assert response.status_code == 200
    assert response.json()["status"] == "closed"

    # Verificar que a conversa ficou fechada
    detail = await client.get(
        f"/api/v1/conversations/{conv_id}",
        headers=API_KEY_HEADERS,
    )
    assert detail.json()["status"] == "closed"


async def test_close_not_found(client):
    response = await client.post(
        "/api/v1/conversations/00000000-0000-0000-0000-000000000000/close",
        headers=API_KEY_HEADERS,
    )
    assert response.status_code == 404


async def test_closed_conversation_not_reused(client):
    """Após fechar, nova mensagem do mesmo user cria conversa nova."""
    conv_id = await _create_conversation(client)

    # Fecha
    await client.post(
        f"/api/v1/conversations/{conv_id}/close",
        headers=API_KEY_HEADERS,
    )

    # Nova mensagem do mesmo user
    with patch("app.api.routes.messages.ai_service") as mock_ai:
        mock_ai.classify_intent = AsyncMock(return_value={
            "intent": "question", "urgency_score": 0.1,
        })
        mock_ai.generate_response = AsyncMock(return_value=("Nova conversa", 50))

        r = await client.post(
            "/api/v1/messages/incoming",
            json=SAMPLE_MESSAGE,
            headers=WEBHOOK_HEADERS,
        )

    assert r.json()["conversation_id"] != conv_id


# ── Cleanup ────────────────────────────────────────────────────────────────

async def test_cleanup_endpoint_returns_count(client):
    response = await client.post(
        "/api/v1/conversations/cleanup",
        headers=WEBHOOK_HEADERS,
    )
    assert response.status_code == 200
    data = response.json()
    assert data["ok"] is True
    assert "conversations_closed" in data
    assert data["conversations_closed"] >= 0
