import structlog
from fastapi import APIRouter, Depends, HTTPException, Header
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.security import verify_webhook_secret
from app.core.tasks import create_tracked_task
from app.db.database import get_db
from app.db.redis_client import get_redis, SessionCache
from app.models.models import IntentEnum, MessageRoleEnum
from app.schemas.schemas import IncomingMessage, BotResponse
from app.services.conversation_service import ConversationService
from app.services.ai_service import AIService
from app.services.slack_service import SlackService

router = APIRouter(prefix="/messages", tags=["messages"])
logger = structlog.get_logger()
settings = get_settings()
ai_service = AIService()
slack_service = SlackService()


@router.post("/incoming", response_model=BotResponse)
async def process_incoming_message(
    msg: IncomingMessage,
    db: AsyncSession = Depends(get_db),
    redis=Depends(get_redis),
    _=Depends(verify_webhook_secret),
):
    """
    Endpoint principal chamado pelo n8n.
    Recebe mensagem normalizada, processa e retorna resposta.
    """
    cache = SessionCache(redis)
    svc = ConversationService(db, cache)

    log = logger.bind(
        channel=msg.channel,
        external_user_id=msg.external_user_id,
    )

    # 1. Usuário e conversa
    user = await svc.get_or_create_user(msg)
    conversation = await svc.get_or_create_conversation(user, msg.channel)

    log = log.bind(conversation_id=str(conversation.id))

    # 2. Se já está em modo humano — apenas registra, bot silente
    if conversation.human_mode:
        log.info("human_mode_active_skip_bot")
        user_msg = await svc.add_message(
            conversation.id,
            MessageRoleEnum.user,
            msg.text,
        )
        return BotResponse(
            conversation_id=str(conversation.id),
            message_id=str(user_msg.id),
            reply="",
            intent=conversation.intent or IntentEnum.unknown,
            urgency_score=conversation.urgency_score,
            human_handoff=True,
            tokens_used=0,
        )

    # 3. Classifica intenção
    classification = await ai_service.classify_intent(msg.text)
    intent = IntentEnum(classification.get("intent", "unknown"))
    urgency_score = float(classification.get("urgency_score", 0.0))

    await svc.add_message(
        conversation.id,
        MessageRoleEnum.user,
        msg.text,
        intent=intent,
        urgency_score=urgency_score,
    )

    # 4. Atualiza intenção da conversa
    await svc.update_intent(conversation, intent, urgency_score)
    log.info("intent_classified", intent=intent.value, urgency_score=urgency_score)

    # 5. Decide handoff
    human_handoff = urgency_score >= settings.human_handoff_urgency_threshold
    if human_handoff:
        log.warning("human_handoff_triggered", urgency_score=urgency_score)
        await svc.trigger_human_handoff(conversation, agent_id="pending")

        # Conta mensagens a partir do cache Redis
        session_data = await cache.get(str(conversation.id))
        msg_count = session_data.get("message_count", 0) if session_data else 0

        # Dispara notificação Slack em background (rastreada para graceful shutdown)
        create_tracked_task(
            slack_service.notify_handoff(
                conversation_id=str(conversation.id),
                channel=msg.channel.value,
                intent=intent.value,
                urgency_score=urgency_score,
                last_message=msg.text,
                user_name=user.name,
                user_email=user.email,
                message_count=msg_count,
            )
        )

    # 6. Gera resposta da IA (histórico já inclui a msg do usuário salva acima)
    history = await svc.get_recent_history(conversation.id, limit=10)
    reply, tokens_used = await ai_service.generate_response(history, intent)

    # 7. Salva resposta do bot
    bot_msg = await svc.add_message(
        conversation.id,
        MessageRoleEnum.bot,
        reply,
        intent=intent,
        tokens_used=tokens_used,
    )

    log.info("response_generated", tokens_used=tokens_used, human_handoff=human_handoff)

    return BotResponse(
        conversation_id=str(conversation.id),
        message_id=str(bot_msg.id),
        reply=reply,
        intent=intent,
        urgency_score=urgency_score,
        human_handoff=human_handoff,
        tokens_used=tokens_used,
    )
