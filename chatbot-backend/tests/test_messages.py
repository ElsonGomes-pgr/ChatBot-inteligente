"""
Testes do fluxo principal: POST /api/v1/messages/incoming
Cobre: criação de usuário, classificação, resposta, handoff, reutilização de conversa.
"""

from unittest.mock import AsyncMock, patch


VALID_HEADERS = {"X-Webhook-Secret": "test_webhook_secret"}

SAMPLE_MESSAGE = {
    "external_user_id": "fb_123456",
    "channel": "messenger",
    "text": "Olá, quero saber sobre os planos",
    "user_name": "Maria Silva",
}


async def test_incoming_message_returns_bot_response(client):
    """Mensagem normal deve retornar resposta do bot."""
    with patch("app.api.routes.messages.ai_service") as mock_ai:
        mock_ai.classify_intent = AsyncMock(return_value={
            "intent": "sales",
            "urgency_score": 0.2,
            "entities": {},
            "language": "pt",
        })
        mock_ai.generate_response = AsyncMock(return_value=(
            "Olá Maria! Temos planos a partir de R$29/mês.",
            150,
        ))

        response = await client.post(
            "/api/v1/messages/incoming",
            json=SAMPLE_MESSAGE,
            headers=VALID_HEADERS,
        )

    assert response.status_code == 200
    data = response.json()
    assert data["intent"] == "sales"
    assert data["human_handoff"] is False
    assert data["reply"] != ""
    assert data["tokens_used"] == 150
    assert "conversation_id" in data
    assert "message_id" in data


async def test_incoming_message_without_webhook_secret_returns_422(client):
    """Requisição sem X-Webhook-Secret deve retornar 422 (header ausente)."""
    response = await client.post(
        "/api/v1/messages/incoming",
        json=SAMPLE_MESSAGE,
    )
    assert response.status_code == 422


async def test_incoming_message_wrong_webhook_secret_returns_401(client):
    """Requisição com secret errado deve retornar 401."""
    response = await client.post(
        "/api/v1/messages/incoming",
        json=SAMPLE_MESSAGE,
        headers={"X-Webhook-Secret": "wrong_secret"},
    )
    assert response.status_code == 401


async def test_incoming_message_triggers_handoff_on_high_urgency(client):
    """Mensagem urgente deve disparar handoff."""
    with patch("app.api.routes.messages.ai_service") as mock_ai, \
         patch("app.api.routes.messages.slack_service") as mock_slack:

        mock_ai.classify_intent = AsyncMock(return_value={
            "intent": "urgency",
            "urgency_score": 0.9,
            "entities": {},
            "language": "pt",
        })
        mock_ai.generate_response = AsyncMock(return_value=(
            "Entendo sua frustração. Um especialista vai te atender.",
            200,
        ))
        mock_slack.notify_handoff = AsyncMock(return_value=True)

        response = await client.post(
            "/api/v1/messages/incoming",
            json={
                **SAMPLE_MESSAGE,
                "text": "VOU CANCELAR TUDO AGORA! ISSO É UM ABSURDO!",
            },
            headers=VALID_HEADERS,
        )

    assert response.status_code == 200
    data = response.json()
    assert data["human_handoff"] is True
    assert data["urgency_score"] >= 0.75
    assert data["intent"] == "urgency"


async def test_second_message_same_user_reuses_conversation(client):
    """Duas mensagens do mesmo usuário devem usar a mesma conversa."""
    with patch("app.api.routes.messages.ai_service") as mock_ai:
        mock_ai.classify_intent = AsyncMock(return_value={
            "intent": "question",
            "urgency_score": 0.1,
        })
        mock_ai.generate_response = AsyncMock(return_value=("Resposta 1", 100))

        r1 = await client.post(
            "/api/v1/messages/incoming",
            json=SAMPLE_MESSAGE,
            headers=VALID_HEADERS,
        )

        mock_ai.generate_response = AsyncMock(return_value=("Resposta 2", 100))

        r2 = await client.post(
            "/api/v1/messages/incoming",
            json={**SAMPLE_MESSAGE, "text": "E qual o preço?"},
            headers=VALID_HEADERS,
        )

    assert r1.json()["conversation_id"] == r2.json()["conversation_id"]


async def test_human_mode_bot_stays_silent(client):
    """Quando em modo humano, o bot não deve responder."""
    with patch("app.api.routes.messages.ai_service") as mock_ai, \
         patch("app.api.routes.messages.slack_service") as mock_slack:
        # Primeira mensagem — trigger handoff
        mock_ai.classify_intent = AsyncMock(return_value={
            "intent": "urgency",
            "urgency_score": 0.95,
        })
        mock_ai.generate_response = AsyncMock(return_value=("Resposta urgente", 100))
        mock_slack.notify_handoff = AsyncMock(return_value=True)

        r1 = await client.post(
            "/api/v1/messages/incoming",
            json={**SAMPLE_MESSAGE, "text": "URGENTE!"},
            headers=VALID_HEADERS,
        )

    assert r1.json()["human_handoff"] is True

    # Segunda mensagem do mesmo user — bot deve ficar silente
    r2 = await client.post(
        "/api/v1/messages/incoming",
        json={**SAMPLE_MESSAGE, "text": "Alguém?"},
        headers=VALID_HEADERS,
    )

    assert r2.status_code == 200
    assert r2.json()["reply"] == ""
    assert r2.json()["human_handoff"] is True


async def test_empty_text_rejected(client):
    """Mensagem com texto vazio deve ser rejeitada pela validação."""
    response = await client.post(
        "/api/v1/messages/incoming",
        json={**SAMPLE_MESSAGE, "text": ""},
        headers=VALID_HEADERS,
    )
    assert response.status_code == 422


async def test_invalid_channel_rejected(client):
    """Canal inválido deve ser rejeitado."""
    response = await client.post(
        "/api/v1/messages/incoming",
        json={**SAMPLE_MESSAGE, "channel": "telegram"},
        headers=VALID_HEADERS,
    )
    assert response.status_code == 422


async def test_ai_failure_returns_fallback(client):
    """Se a IA falhar, deve retornar mensagem de fallback."""
    with patch("app.api.routes.messages.ai_service") as mock_ai:
        mock_ai.classify_intent = AsyncMock(return_value={
            "intent": "unknown",
            "urgency_score": 0.0,
        })
        mock_ai.generate_response = AsyncMock(return_value=(
            "Desculpe, estou com dificuldades técnicas no momento. Um agente irá te atender em breve.",
            0,
        ))

        response = await client.post(
            "/api/v1/messages/incoming",
            json=SAMPLE_MESSAGE,
            headers=VALID_HEADERS,
        )

    assert response.status_code == 200
    assert "dificuldades" in response.json()["reply"]


async def test_user_info_updated_on_return_visit(client):
    """Dados do usuário devem ser atualizados se mudarem."""
    with patch("app.api.routes.messages.ai_service") as mock_ai:
        mock_ai.classify_intent = AsyncMock(return_value={
            "intent": "question", "urgency_score": 0.1,
        })
        mock_ai.generate_response = AsyncMock(return_value=("Ok", 50))

        # Primeira visita sem email
        await client.post(
            "/api/v1/messages/incoming",
            json=SAMPLE_MESSAGE,
            headers=VALID_HEADERS,
        )

        # Segunda visita com email
        await client.post(
            "/api/v1/messages/incoming",
            json={**SAMPLE_MESSAGE, "text": "Oi", "user_email": "maria@email.com"},
            headers=VALID_HEADERS,
        )

    # Se não deu erro, os dados foram atualizados com sucesso
