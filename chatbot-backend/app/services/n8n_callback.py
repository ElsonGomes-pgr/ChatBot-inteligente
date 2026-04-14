"""
N8nCallbackService — notifica o n8n quando eventos acontecem no backend.

Fluxo de resposta do agente:
  1. Agente envia POST /api/v1/conversations/{id}/reply
  2. Backend salva no DB e chama N8nCallbackService.notify_agent_reply()
  3. n8n recebe o webhook e entrega a mensagem no canal original (Messenger/WhatsApp/Website)
"""

import asyncio
import httpx
import structlog
from app.core.config import get_settings

logger = structlog.get_logger()
settings = get_settings()

MAX_RETRIES = 3
RETRY_BACKOFF_BASE = 2  # segundos: 2, 4, 8


class N8nCallbackService:

    def __init__(self):
        self.callback_url = settings.n8n_callback_url

    async def notify_agent_reply(
        self,
        *,
        conversation_id: str,
        channel: str,
        text: str,
        agent_id: str,
        external_user_id: str,
    ) -> bool:
        """
        Envia webhook para o n8n quando o agente humano responde.
        O n8n usa esses dados para entregar a mensagem no canal do usuário.
        Retenta até 3x com backoff exponencial em caso de falha.
        """
        if not self.callback_url:
            logger.warning("n8n_callback_url_not_configured")
            return False

        payload = {
            "event": "agent_reply",
            "conversation_id": conversation_id,
            "channel": channel,
            "text": text,
            "agent_id": agent_id,
            "external_user_id": external_user_id,
        }

        last_error = None
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                async with httpx.AsyncClient(timeout=10) as client:
                    r = await client.post(
                        self.callback_url,
                        json=payload,
                        headers={
                            "X-Webhook-Secret": settings.n8n_webhook_secret,
                        },
                    )
                    r.raise_for_status()
                    logger.info("n8n_callback_sent", event="agent_reply",
                                conversation_id=conversation_id,
                                attempt=attempt)
                    return True
            except Exception as e:
                last_error = e
                if attempt < MAX_RETRIES:
                    wait = RETRY_BACKOFF_BASE ** attempt
                    logger.warning("n8n_callback_retry",
                                   error=str(e),
                                   conversation_id=conversation_id,
                                   attempt=attempt,
                                   next_retry_seconds=wait)
                    await asyncio.sleep(wait)

        logger.error("n8n_callback_failed_all_retries",
                     error=str(last_error),
                     conversation_id=conversation_id,
                     attempts=MAX_RETRIES)
        return False
