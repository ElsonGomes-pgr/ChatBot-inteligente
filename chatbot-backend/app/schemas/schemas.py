from pydantic import BaseModel, Field
from app.models.models import ChannelEnum, IntentEnum


class IncomingMessage(BaseModel):
    external_user_id: str = Field(..., description="ID do usuário no canal externo")
    channel: ChannelEnum
    text: str = Field(..., min_length=1)
    user_name: str | None = None
    user_email: str | None = None
    user_phone: str | None = None
    metadata: dict = Field(default_factory=dict)


class BotResponse(BaseModel):
    conversation_id: str
    message_id: str
    reply: str
    intent: IntentEnum
    urgency_score: float
    human_handoff: bool
    tokens_used: int


class AgentReply(BaseModel):
    """Mensagem enviada pelo agente humano de volta ao usuário."""
    text: str = Field(..., min_length=1, max_length=4000)
    agent_id: str = Field(..., description="ID do agente (Slack user ID ou interno)")
