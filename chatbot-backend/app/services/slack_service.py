"""
SlackService — envia notificações de handoff para o Slack usando Block Kit.

Fluxo:
  1. Bot detecta urgência → backend chama trigger_human_handoff()
  2. trigger_human_handoff() chama SlackService.notify_handoff()
  3. Slack recebe mensagem rica com dados da conversa + botões de ação
  4. Agente clica "Assumir" → Slack chama o endpoint /api/v1/slack/actions
  5. Backend atualiza a conversa com o agente e confirma no Slack
"""

import httpx
import structlog
from app.core.config import get_settings

logger = structlog.get_logger()
settings = get_settings()

INTENT_EMOJI = {
    "support":  "🔧",
    "sales":    "💼",
    "question": "❓",
    "urgency":  "🚨",
    "unknown":  "❔",
}

CHANNEL_EMOJI = {
    "messenger": "💬 Messenger",
    "website":   "🌐 Website",
    "whatsapp":  "📱 WhatsApp",
    "api":       "⚙️ API",
}

URGENCY_BAR = {
    (0.0, 0.3):  ("🟢", "Baixa"),
    (0.3, 0.6):  ("🟡", "Média"),
    (0.6, 0.75): ("🟠", "Alta"),
    (0.75, 1.01):("🔴", "Crítica"),
}


def _urgency_label(score: float) -> tuple[str, str]:
    for (lo, hi), label in URGENCY_BAR.items():
        if lo <= score < hi:
            return label
    return ("🔴", "Crítica")


class SlackService:

    def __init__(self):
        self.webhook_url = settings.slack_webhook_url
        self.bot_token = settings.slack_bot_token
        self.channel = settings.slack_handoff_channel

    async def notify_handoff(
        self,
        *,
        conversation_id: str,
        channel: str,
        intent: str,
        urgency_score: float,
        last_message: str,
        user_name: str | None,
        user_email: str | None,
        message_count: int,
    ) -> bool:
        """
        Envia mensagem Block Kit para o Slack com botão de ação "Assumir conversa".
        Retorna True se enviou com sucesso.
        """
        urgency_icon, urgency_text = _urgency_label(urgency_score)
        intent_icon = INTENT_EMOJI.get(intent, "❔")
        channel_label = CHANNEL_EMOJI.get(channel, channel)

        user_line = user_name or "Visitante anônimo"
        if user_email:
            user_line += f" ({user_email})"

        # Trunca a última mensagem para o preview
        preview = last_message[:200] + ("…" if len(last_message) > 200 else "")

        blocks = [
            {
                "type": "header",
                "text": {
                    "type": "plain_text",
                    "text": f"{urgency_icon} Handoff solicitado — atendimento humano necessário",
                    "emoji": True,
                }
            },
            {"type": "divider"},
            {
                "type": "section",
                "fields": [
                    {"type": "mrkdwn", "text": f"*Canal*\n{channel_label}"},
                    {"type": "mrkdwn", "text": f"*Intenção*\n{intent_icon} {intent.capitalize()}"},
                    {"type": "mrkdwn", "text": f"*Urgência*\n{urgency_icon} {urgency_text} ({urgency_score:.2f})"},
                    {"type": "mrkdwn", "text": f"*Mensagens trocadas*\n{message_count}"},
                    {"type": "mrkdwn", "text": f"*Usuário*\n{user_line}"},
                    {"type": "mrkdwn", "text": f"*Conversa ID*\n`{conversation_id[:8]}…`"},
                ],
            },
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"*Última mensagem do usuário:*\n_{preview}_",
                }
            },
            {"type": "divider"},
            {
                "type": "actions",
                "block_id": f"handoff_{conversation_id}",
                "elements": [
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "✋ Assumir conversa", "emoji": True},
                        "style": "primary",
                        "action_id": "assume_conversation",
                        "value": conversation_id,
                        "confirm": {
                            "title": {"type": "plain_text", "text": "Confirmar"},
                            "text": {"type": "plain_text", "text": "Você irá assumir essa conversa. O bot será pausado."},
                            "confirm": {"type": "plain_text", "text": "Assumir"},
                            "deny": {"type": "plain_text", "text": "Cancelar"},
                        }
                    },
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "👁 Ver histórico", "emoji": True},
                        "action_id": "view_history",
                        "url": f"{settings.app_base_url}/api/v1/conversations/{conversation_id}",
                    },
                ],
            },
        ]

        payload = {"blocks": blocks}

        # Se tiver canal configurado (bot token), usa chat.postMessage
        # Caso contrário, usa Incoming Webhook (mais simples)
        if self.bot_token and self.channel:
            return await self._post_with_bot_token(payload)
        elif self.webhook_url:
            return await self._post_with_webhook(payload)
        else:
            logger.warning("slack_not_configured")
            return False

    async def _post_with_webhook(self, payload: dict) -> bool:
        """Incoming Webhook — mais simples, sem bot token."""
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                r = await client.post(self.webhook_url, json=payload)
                r.raise_for_status()
                logger.info("slack_webhook_sent")
                return True
        except Exception as e:
            logger.error("slack_webhook_failed", error=str(e))
            return False

    async def _post_with_bot_token(self, payload: dict) -> bool:
        """Bot token — permite editar mensagem depois (ex: marcar como assumida)."""
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                r = await client.post(
                    "https://slack.com/api/chat.postMessage",
                    headers={
                        "Authorization": f"Bearer {self.bot_token}",
                        "Content-Type": "application/json",
                    },
                    json={"channel": self.channel, **payload},
                )
                data = r.json()
                if not data.get("ok"):
                    logger.error("slack_api_error", error=data.get("error"))
                    return False
                logger.info("slack_message_sent", ts=data.get("ts"))
                return True
        except Exception as e:
            logger.error("slack_bot_token_failed", error=str(e))
            return False

    async def update_message_assumed(
        self,
        *,
        channel_id: str,
        message_ts: str,
        agent_name: str,
        conversation_id: str,
    ) -> None:
        """
        Edita a mensagem original no Slack para marcar como assumida.
        Chamado pelo endpoint /slack/actions após o agente clicar em "Assumir".
        """
        blocks = [
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"✅ *Conversa assumida por {agent_name}*\nID: `{conversation_id[:8]}…`",
                }
            }
        ]
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                await client.post(
                    "https://slack.com/api/chat.update",
                    headers={
                        "Authorization": f"Bearer {self.bot_token}",
                        "Content-Type": "application/json",
                    },
                    json={"channel": channel_id, "ts": message_ts, "blocks": blocks},
                )
        except Exception as e:
            logger.error("slack_update_failed", error=str(e))
