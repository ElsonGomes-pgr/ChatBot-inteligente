"""
N8nCallbackService — notifica o n8n quando eventos acontecem no backend.

Fluxo de resposta do agente:
  1. Agente envia POST /api/v1/conversations/{id}/reply
  2. Backend salva no DB e chama N8nCallbackService.notify_agent_reply()
  3. n8n recebe o webhook e entrega a mensagem no canal original (Messenger/WhatsApp/Website)
"""

import httpx
import structlog
from app.core.config import get_settings

logger = structlog.get_logger()
settings = get_settings()


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
                            conversation_id=conversation_id)
                return True
        except Exception as e:
            logger.error("n8n_callback_failed", error=str(e),
                         conversation_id=conversation_id)
            return False
