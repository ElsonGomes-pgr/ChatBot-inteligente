# Chatbot Backend — FastAPI + PostgreSQL + Redis

Backend principal do sistema de chatbot inteligente multi-canal.

## Stack
- **Python 3.12** + **FastAPI** — API assíncrona
- **PostgreSQL 16** — persistência principal
- **Redis 7** — sessões, cache e rate limiting
- **n8n** — orquestrador de automação (incluído no compose)
- **SQLAlchemy 2 async** — ORM
- **Alembic** — migrations de banco
- **Claude / OpenAI** — IA para classificação e respostas (com prompt cache + retry)
- **Slack Block Kit** — notificações de handoff para agentes

## Subir o ambiente

```bash
# 1. Copie e configure o .env
cp .env.example .env
# Preencha: ANTHROPIC_API_KEY, API_KEY, SLACK_*, META_APP_SECRET

# 2. Suba tudo
docker compose up --build -d

# 3. Aplique as migrations
make migrate

# 4. Verificar
curl http://localhost:8000/health
# → {"status":"ok","database":"ok","redis":"ok","version":"1.0.0"}
```

## Estrutura do projeto
```
chatbot-backend/
├── app/
│   ├── main.py                        # Entry point FastAPI
│   ├── core/
│   │   ├── config.py                  # Settings (pydantic-settings)
│   │   ├── security.py                # Auth, rate limiting, Meta HMAC
│   │   └── tasks.py                   # Background task tracking
│   ├── db/
│   │   ├── database.py                # Engine async + session
│   │   └── redis_client.py            # Redis pool + SessionCache
│   ├── models/
│   │   └── models.py                  # SQLAlchemy ORM
│   ├── schemas/
│   │   └── schemas.py                 # Pydantic request/response
│   ├── services/
│   │   ├── ai_service.py              # Claude/OpenAI (prompt cache + retry)
│   │   ├── conversation_service.py    # Regras de negócio
│   │   ├── slack_service.py           # Notificações Block Kit
│   │   ├── n8n_callback.py            # Webhook de saída → n8n
│   │   └── timeout_service.py         # Auto-fecha conversas inativas
│   └── api/routes/
│       ├── messages.py                # POST /messages/incoming
│       ├── conversations.py           # CRUD conversas + reply agente
│       ├── health.py                  # GET /health
│       └── slack.py                   # POST /slack/actions
├── alembic/                           # Migrations
├── tests/                             # Testes de integração
├── static/                            # Widget JS do chat
├── n8n/                               # Workflows exportados
├── docker-compose.yml
├── Dockerfile
├── Makefile
└── requirements.txt
```

## Autenticação

O sistema usa dois mecanismos de autenticação:

| Header | Quem usa | Endpoints |
|--------|----------|-----------|
| `X-Webhook-Secret` | n8n → backend | `POST /messages/incoming`, `POST /conversations/{id}/handoff`, `POST /conversations/cleanup` |
| `X-API-Key` | Painel / agentes | `GET /conversations/`, `GET /conversations/{id}`, `POST /conversations/{id}/reply`, `POST /conversations/{id}/close` |

O Slack valida via `X-Slack-Signature` (assinatura HMAC própria).

## Endpoints

| Método | Endpoint | Auth | Descrição |
|--------|----------|------|-----------|
| `GET` | `/health` | — | Status de saúde |
| `POST` | `/api/v1/messages/incoming` | Webhook | Recebe mensagem do n8n |
| `GET` | `/api/v1/conversations/` | API Key | Lista conversas (filtro: `?status=active`) |
| `GET` | `/api/v1/conversations/{id}` | API Key | Histórico completo |
| `POST` | `/api/v1/conversations/{id}/reply` | API Key | Agente responde ao usuário |
| `POST` | `/api/v1/conversations/{id}/handoff` | Webhook | Transfere para humano |
| `POST` | `/api/v1/conversations/{id}/close` | API Key | Encerra conversa |
| `POST` | `/api/v1/conversations/cleanup` | Webhook | Fecha conversas inativas (cron) |
| `POST` | `/api/v1/slack/actions` | Slack Sig | Recebe ações do Slack |

## Fluxo de handoff completo

```
1. Usuário envia mensagem (Messenger/WhatsApp/Website)
2. n8n normaliza e envia POST /messages/incoming
3. IA classifica intenção + urgência
4. Se urgência >= 0.75:
   a. Backend marca conversa como human_mode
   b. Envia notificação rich (Block Kit) para canal Slack
   c. Agente clica "Assumir" no Slack
   d. Slack chama POST /slack/actions → backend confirma
5. Agente responde via POST /conversations/{id}/reply
6. Backend notifica n8n via webhook (N8N_CALLBACK_URL)
7. n8n entrega resposta no canal original do usuário
```

## Exemplo de chamada (n8n → backend)

```json
POST /api/v1/messages/incoming
Headers: X-Webhook-Secret: <valor do .env>

{
  "external_user_id": "fb_123456789",
  "channel": "messenger",
  "text": "Olá, quero saber sobre os planos",
  "user_name": "Maria Silva",
  "metadata": {}
}
```

Resposta:
```json
{
  "conversation_id": "uuid...",
  "message_id": "uuid...",
  "reply": "Olá Maria! Fico feliz em ajudar...",
  "intent": "sales",
  "urgency_score": 0.1,
  "human_handoff": false,
  "tokens_used": 312
}
```

## Exemplo de resposta do agente

```json
POST /api/v1/conversations/{id}/reply
Headers: X-API-Key: <valor do .env>

{
  "text": "Olá Maria, vou resolver seu problema agora.",
  "agent_id": "U_SLACK_ID"
}
```

## Configuração importante

| Variável | Obrigatória | Descrição |
|----------|-------------|-----------|
| `API_KEY` | **Sim** | Chave para endpoints administrativos |
| `ANTHROPIC_API_KEY` ou `OPENAI_API_KEY` | **Sim** | Chave da IA |
| `N8N_WEBHOOK_SECRET` | **Sim** | Secret partilhado n8n ↔ backend |
| `N8N_CALLBACK_URL` | Recomendado | URL do n8n para respostas do agente |
| `META_APP_SECRET` | Em produção | App Secret da Meta para validar webhooks |
| `SLACK_BOT_TOKEN` | Se usar Slack | Token do Slack Bot |
| `CONVERSATION_TIMEOUT_MINUTES` | Não (default: 30) | Auto-fecha conversas inativas |
| `RATE_LIMIT_PER_MINUTE` | Não (default: 60) | Limite de requests por IP |
| `UVICORN_WORKERS` | Não (default: 1) | Workers do Uvicorn em produção |

## Rodar testes

```bash
# No container
make test

# Localmente
pip install -r requirements.txt
pytest tests/ -v
```

## Migrations

```bash
make migrate                      # Aplica migrations pendentes
make revision MSG="descrição"     # Cria nova migration
make history                      # Ver histórico
make current                      # Migration atual no banco
```
