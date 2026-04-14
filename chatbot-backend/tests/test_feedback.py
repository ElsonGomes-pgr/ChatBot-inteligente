"""
Testes do sistema de feedback.
Cobre: criação, duplicata, validação, stats.
"""

from unittest.mock import AsyncMock, patch


WEBHOOK_HEADERS = {"X-Webhook-Secret": "test_webhook_secret"}
API_KEY_HEADERS = {"X-API-Key": "test_api_key"}

SAMPLE_MESSAGE = {
    "external_user_id": "fb_feedback_user",
    "channel": "messenger",
    "text": "Preciso de ajuda",
    "user_name": "João",
}


async def _create_conversation(client) -> str:
    """Helper: cria uma conversa e retorna o ID."""
    with patch("app.api.routes.messages.ai_service") as mock_ai:
        mock_ai.classify_intent = AsyncMock(return_value={
            "intent": "support",
            "urgency_score": 0.2,
        })
        mock_ai.generate_response = AsyncMock(return_value=("Olá!", 50))

        r = await client.post(
            "/api/v1/messages/incoming",
            json=SAMPLE_MESSAGE,
            headers=WEBHOOK_HEADERS,
        )
    return r.json()["conversation_id"]


async def test_create_feedback_success(client):
    """Feedback válido deve ser criado com sucesso."""
    conv_id = await _create_conversation(client)

    response = await client.post(
        f"/api/v1/conversations/{conv_id}/feedback",
        json={"rating": 5, "comment": "Excelente atendimento!"},
        headers=WEBHOOK_HEADERS,
    )

    assert response.status_code == 200
    data = response.json()
    assert data["rating"] == 5
    assert data["comment"] == "Excelente atendimento!"
    assert data["resolved_by"] == "bot"
    assert data["conversation_id"] == conv_id


async def test_create_feedback_without_comment(client):
    """Feedback sem comentário deve funcionar."""
    conv_id = await _create_conversation(client)

    response = await client.post(
        f"/api/v1/conversations/{conv_id}/feedback",
        json={"rating": 3},
        headers=WEBHOOK_HEADERS,
    )

    assert response.status_code == 200
    assert response.json()["comment"] is None


async def test_duplicate_feedback_rejected(client):
    """Segundo feedback para a mesma conversa deve retornar 409."""
    conv_id = await _create_conversation(client)

    await client.post(
        f"/api/v1/conversations/{conv_id}/feedback",
        json={"rating": 4},
        headers=WEBHOOK_HEADERS,
    )

    response = await client.post(
        f"/api/v1/conversations/{conv_id}/feedback",
        json={"rating": 2},
        headers=WEBHOOK_HEADERS,
    )

    assert response.status_code == 409


async def test_feedback_invalid_rating_rejected(client):
    """Rating fora de 1-5 deve ser rejeitado."""
    conv_id = await _create_conversation(client)

    r_zero = await client.post(
        f"/api/v1/conversations/{conv_id}/feedback",
        json={"rating": 0},
        headers=WEBHOOK_HEADERS,
    )
    assert r_zero.status_code == 422

    r_six = await client.post(
        f"/api/v1/conversations/{conv_id}/feedback",
        json={"rating": 6},
        headers=WEBHOOK_HEADERS,
    )
    assert r_six.status_code == 422


async def test_feedback_nonexistent_conversation(client):
    """Feedback para conversa inexistente deve retornar 404."""
    response = await client.post(
        "/api/v1/conversations/00000000-0000-0000-0000-000000000000/feedback",
        json={"rating": 5},
        headers=WEBHOOK_HEADERS,
    )
    assert response.status_code == 404


async def test_feedback_without_auth_rejected(client):
    """Feedback sem webhook secret deve ser rejeitado."""
    response = await client.post(
        "/api/v1/conversations/some-id/feedback",
        json={"rating": 5},
    )
    assert response.status_code == 422


async def test_feedback_stats_empty(client):
    """Stats sem feedbacks deve retornar zeros."""
    response = await client.get(
        "/api/v1/feedback/stats",
        headers=API_KEY_HEADERS,
    )

    assert response.status_code == 200
    data = response.json()
    assert data["total_feedbacks"] == 0
    assert data["avg_rating"] == 0.0
    assert data["csat_score"] == 0.0


async def test_feedback_stats_with_data(client):
    """Stats deve calcular métricas corretamente."""
    # Cria 3 conversas com feedbacks diferentes
    for rating in [5, 4, 2]:
        conv_id = await _create_conversation(client)
        # Muda o external_user_id para criar conversas separadas
        SAMPLE_MESSAGE["external_user_id"] = f"user_{rating}"
        conv_id = await _create_conversation(client)

        await client.post(
            f"/api/v1/conversations/{conv_id}/feedback",
            json={"rating": rating},
            headers=WEBHOOK_HEADERS,
        )

    response = await client.get(
        "/api/v1/feedback/stats",
        headers=API_KEY_HEADERS,
    )

    assert response.status_code == 200
    data = response.json()
    assert data["total_feedbacks"] == 3
    assert data["positive_count"] == 2  # rating 4 e 5
    assert data["negative_count"] == 1  # rating 2
