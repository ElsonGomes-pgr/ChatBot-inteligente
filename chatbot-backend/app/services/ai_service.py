import json
import structlog
from pydantic import BaseModel, Field, ValidationError
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
from app.core.config import get_settings
from app.models.models import IntentEnum

logger = structlog.get_logger()
settings = get_settings()

INTENT_SYSTEM_PROMPT = """Você é um classificador de intenções para um sistema de atendimento ao cliente.

Analise a mensagem do usuário e retorne APENAS um JSON válido no seguinte formato:
{
  "intent": "<support|sales|question|urgency|unknown>",
  "urgency_score": <float entre 0.0 e 1.0>,
  "entities": {<entidades relevantes extraídas>},
  "language": "<pt|en|es>"
}

Critérios de urgência_score:
- 0.0–0.3: conversa normal, sem urgência
- 0.3–0.6: alguma insatisfação ou problema em andamento
- 0.6–0.75: problema sério, usuário frustrado
- 0.75–1.0: URGENTE — ameaça de cancelamento, problema crítico, linguagem agressiva, risco financeiro

Definições de intent:
- support: problema técnico, reclamação, pedido de ajuda
- sales: interesse em comprar, planos, preços, upgrade
- question: dúvida geral, como funciona, informação
- urgency: qualquer intent acima com urgency_score >= 0.75
- unknown: não foi possível classificar

Retorne SOMENTE o JSON, sem texto adicional."""


INTENT_SYSTEM_PROMPTS_BY_INTENT = {
    IntentEnum.support: """Você é um assistente de suporte técnico especializado.
Foque em: entender o problema, coletar informações necessárias, oferecer soluções práticas.
Seja empático e objetivo. Se não souber a solução, diga honestamente e ofereça alternativas.""",

    IntentEnum.sales: """Você é um consultor de vendas especializado.
Foque em: entender a necessidade do cliente, apresentar os benefícios relevantes, criar próximos passos claros.
Seja consultivo, não pressione. Pergunte sobre o contexto e ofereça a solução mais adequada.""",

    IntentEnum.question: """Você é um assistente informativo.
Responda de forma clara, direta e precisa. Use exemplos quando útil.
Se não souber a resposta, diga claramente e ofereça alternativas.""",

    IntentEnum.urgency: """Você está atendendo um cliente em situação urgente.
PRIORIDADE: validar a experiência do cliente, demonstrar que está sendo ouvido.
Seja empático, direto e rápido. Informe que um especialista irá assumir em breve.""",

    IntentEnum.unknown: """Você é um assistente de atendimento ao cliente.
Responda de forma amigável e tente entender melhor o que o usuário precisa.""",
}

BASE_SYSTEM_PROMPT = """Você é um assistente virtual de atendimento ao cliente.

Diretrizes:
- Responda sempre em português (ou no idioma do usuário)
- Seja cordial, claro e objetivo
- NUNCA invente informações sobre produtos, preços ou políticas
- Se não souber algo, diga honestamente
- Limite suas respostas a 3 parágrafos no máximo
- Não use markdown excessivo — a resposta será exibida em um chat"""


class ClassificationResult(BaseModel):
    """Valida a resposta de classificação da IA."""
    intent: str = Field(default="unknown")
    urgency_score: float = Field(default=0.0, ge=0.0, le=1.0)
    entities: dict = Field(default_factory=dict)
    language: str = Field(default="pt")


# Retry: tenta 3x com backoff exponencial (1s, 2s, 4s) para erros de rede/rate-limit
_RETRY_POLICY = dict(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=1, max=10),
    retry=retry_if_exception_type((TimeoutError, ConnectionError)),
    reraise=True,
)


class AIService:

    def __init__(self):
        self.provider = settings.ai_provider
        self._anthropic_client = None
        self._openai_client = None

    def _get_anthropic(self):
        if not self._anthropic_client:
            import anthropic
            self._anthropic_client = anthropic.AsyncAnthropic(
                api_key=settings.anthropic_api_key,
                timeout=30.0,
            )
        return self._anthropic_client

    def _get_openai(self):
        if not self._openai_client:
            from openai import AsyncOpenAI
            self._openai_client = AsyncOpenAI(
                api_key=settings.openai_api_key,
                timeout=30.0,
            )
        return self._openai_client

    async def classify_intent(self, user_message: str) -> dict:
        """Chamada leve e rápida apenas para classificação."""
        try:
            if self.provider == "anthropic":
                raw = await self._classify_anthropic(user_message)
            else:
                raw = await self._classify_openai(user_message)

            # Valida e normaliza a resposta
            result = ClassificationResult(**raw).model_dump()

            # Garante que urgency vira intent se score alto
            if result["urgency_score"] >= settings.human_handoff_urgency_threshold:
                result["intent"] = "urgency"

            return result

        except (ValidationError, json.JSONDecodeError) as e:
            logger.warning("intent_classification_parse_error", error=str(e))
            return ClassificationResult().model_dump()
        except Exception as e:
            logger.error("intent_classification_failed", error=str(e))
            return ClassificationResult().model_dump()

    @retry(**_RETRY_POLICY)
    async def _classify_anthropic(self, text: str) -> dict:
        client = self._get_anthropic()
        response = await client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=256,
            system=[{
                "type": "text",
                "text": INTENT_SYSTEM_PROMPT,
                "cache_control": {"type": "ephemeral"},
            }],
            messages=[{"role": "user", "content": text}],
        )
        raw = response.content[0].text.strip()
        return json.loads(raw)

    @retry(**_RETRY_POLICY)
    async def _classify_openai(self, text: str) -> dict:
        client = self._get_openai()
        response = await client.chat.completions.create(
            model="gpt-4o-mini",
            max_tokens=256,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": INTENT_SYSTEM_PROMPT},
                {"role": "user", "content": text},
            ],
        )
        return json.loads(response.choices[0].message.content)

    async def generate_response(
        self,
        history: list[dict],
        intent: IntentEnum,
    ) -> tuple[str, int]:
        """Gera resposta contextualizada. O histórico já inclui a última mensagem do usuário."""
        intent_prompt = INTENT_SYSTEM_PROMPTS_BY_INTENT.get(intent, "")
        system = f"{BASE_SYSTEM_PROMPT}\n\n{intent_prompt}"

        try:
            if self.provider == "anthropic":
                return await self._generate_anthropic(system, history)
            else:
                return await self._generate_openai(system, history)

        except Exception as e:
            logger.error("response_generation_failed", error=str(e))
            fallback = "Desculpe, estou com dificuldades técnicas no momento. Um agente irá te atender em breve."
            return fallback, 0

    @retry(**_RETRY_POLICY)
    async def _generate_anthropic(self, system: str, messages: list) -> tuple[str, int]:
        client = self._get_anthropic()
        response = await client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=1024,
            system=[{
                "type": "text",
                "text": system,
                "cache_control": {"type": "ephemeral"},
            }],
            messages=messages,
        )
        text = response.content[0].text
        tokens = response.usage.input_tokens + response.usage.output_tokens
        return text, tokens

    @retry(**_RETRY_POLICY)
    async def _generate_openai(self, system: str, messages: list) -> tuple[str, int]:
        client = self._get_openai()
        full_messages = [{"role": "system", "content": system}] + messages
        response = await client.chat.completions.create(
            model="gpt-4o",
            max_tokens=1024,
            messages=full_messages,
        )
        text = response.choices[0].message.content
        tokens = response.usage.total_tokens
        return text, tokens
