"""Testes do N8nCallbackService com retry."""

import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from app.services.n8n_callback import N8nCallbackService


@pytest.fixture
def callback_service():
    with patch("app.services.n8n_callback.settings") as mock_settings:
        mock_settings.n8n_callback_url = "http://n8n:5678/webhook/reply"
        mock_settings.n8n_webhook_secret = "test_secret"
        svc = N8nCallbackService()
        svc.callback_url = "http://n8n:5678/webhook/reply"
        yield svc


REPLY_KWARGS = dict(
    conversation_id="abc-123",
    channel="messenger",
    text="Olá, vou resolver.",
    agent_id="U_AGENT_01",
    external_user_id="fb_123",
)


@pytest.mark.asyncio
async def test_successful_callback(callback_service):
    """Callback bem-sucedido na primeira tentativa."""
    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()

    with patch("app.services.n8n_callback.httpx.AsyncClient") as mock_client_class:
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client_class.return_value = mock_client

        result = await callback_service.notify_agent_reply(**REPLY_KWARGS)

    assert result is True


@pytest.mark.asyncio
async def test_callback_retries_on_failure(callback_service):
    """Callback deve retentar em caso de falha."""
    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()

    call_count = 0

    async def side_effect(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count < 3:
            raise ConnectionError("n8n unreachable")
        return mock_response

    with patch("app.services.n8n_callback.httpx.AsyncClient") as mock_client_class, \
         patch("app.services.n8n_callback.asyncio.sleep", new_callable=AsyncMock):
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(side_effect=side_effect)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client_class.return_value = mock_client

        result = await callback_service.notify_agent_reply(**REPLY_KWARGS)

    assert result is True
    assert call_count == 3


@pytest.mark.asyncio
async def test_callback_fails_after_max_retries(callback_service):
    """Callback deve falhar após esgotar tentativas."""
    with patch("app.services.n8n_callback.httpx.AsyncClient") as mock_client_class, \
         patch("app.services.n8n_callback.asyncio.sleep", new_callable=AsyncMock):
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(side_effect=ConnectionError("n8n down"))
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client_class.return_value = mock_client

        result = await callback_service.notify_agent_reply(**REPLY_KWARGS)

    assert result is False


@pytest.mark.asyncio
async def test_callback_returns_false_when_not_configured():
    """Sem URL configurada, deve retornar False."""
    with patch("app.services.n8n_callback.settings") as mock_settings:
        mock_settings.n8n_callback_url = ""
        svc = N8nCallbackService()
        svc.callback_url = ""

        result = await svc.notify_agent_reply(**REPLY_KWARGS)

    assert result is False
