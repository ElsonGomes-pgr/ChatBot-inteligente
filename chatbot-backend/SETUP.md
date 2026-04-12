# Guia de Configuração — n8n Workflows

## 1. Subir o ambiente

```bash
cd chatbot-backend
docker compose up --build -d

# Verificar saúde
curl http://localhost:8000/health
# → {"status":"ok","database":"ok","redis":"ok","version":"1.0.0"}
```

## 2. Acessar o n8n

Abrir: http://localhost:5678
- Usuário: `admin` (definido em .env → N8N_USER)
- Senha: `admin_secret_change_me` (definido em .env → N8N_PASSWORD)

## 3. Configurar variáveis de ambiente no n8n

No n8n: Settings → Environment Variables → adicionar:

| Variável | Valor |
|---|---|
| `N8N_WEBHOOK_SECRET` | mesmo valor do .env do backend |
| `META_VERIFY_TOKEN` | qualquer string aleatória (você define) |
| `META_PAGE_ACCESS_TOKEN` | gerado no Meta Developer Console |

## 4. Importar os workflows

1. No n8n: menu superior → **Import from file**
2. Importar `workflow-messenger.json`
3. Importar `workflow-website.json`
4. Ativar cada workflow (toggle no canto superior direito)

## 5. URLs dos webhooks após importar

Após ativar, o n8n mostra as URLs de produção:

- **Messenger:** `https://SEU_N8N/webhook/messenger`
- **Website:** `https://SEU_N8N/webhook/website-chat`

> Em desenvolvimento local, use **ngrok** para expor o n8n:
> ```bash
> ngrok http 5678
> # Copia a URL https://xxxx.ngrok.io
> ```

---

## 6. Configurar Facebook Messenger

### 6.1 Criar app no Meta for Developers

1. Acesse: https://developers.facebook.com
2. **Meus Apps → Criar App → Empresa**
3. Adicione o produto **Messenger**

### 6.2 Configurar webhook

1. Em Messenger → Configurações → Webhooks → **Editar**
2. **URL de Callback:** `https://SEU_N8N/webhook/messenger`
3. **Token de Verificação:** o valor que você definiu em `META_VERIFY_TOKEN`
4. Campos a assinar: `messages`, `messaging_postbacks`
5. Clique em **Verificar e salvar**

> O n8n responde automaticamente o challenge de verificação ✓

### 6.3 Gerar Page Access Token

1. Em Messenger → Configurações → Tokens de Acesso
2. Selecione sua página → **Gerar token**
3. Copie o token e cole no n8n → Environment Variables → `META_PAGE_ACCESS_TOKEN`

### 6.4 Testar

```bash
# Simula mensagem vinda do Messenger
curl -X POST https://SEU_N8N/webhook/messenger \
  -H "Content-Type: application/json" \
  -d '{
    "entry": [{
      "messaging": [{
        "sender": {"id": "user_test_001"},
        "message": {"text": "Olá, preciso de ajuda!"},
        "timestamp": 1714000000
      }]
    }]
  }'
```

---

## 7. Configurar Chat do Website

### 7.1 Incluir o widget no site

```html
<!-- Antes do </body> -->
<script>
  window.ChatbotConfig = {
    n8nUrl: 'https://SEU_N8N/webhook/website-chat',
    title: 'Suporte',
    primaryColor: '#4F46E5'
  };
</script>
<script src="/chatbot-widget.js"></script>
```

### 7.2 Passar dados do usuário logado (opcional)

```html
<script>
  window.ChatbotConfig = {
    n8nUrl: 'https://SEU_N8N/webhook/website-chat',
    title: 'Suporte',
    primaryColor: '#4F46E5',
    userName: 'João Silva',   // se usuário estiver logado
    userEmail: 'joao@email.com'
  };
</script>
```

### 7.3 Testar o widget

```bash
curl -X POST http://localhost:5678/webhook/website-chat \
  -H "Content-Type: application/json" \
  -d '{
    "visitor_id": "v_test_abc123",
    "text": "Qual o preço do plano pro?",
    "page_url": "https://seusite.com/planos"
  }'
```

Resposta esperada:
```json
{
  "ok": true,
  "conversation_id": "uuid...",
  "reply": "Olá! Nosso plano Pro custa...",
  "intent": "sales",
  "human_handoff": false
}
```

---

## 8. Verificar que tudo funciona

```bash
# Health do backend
curl http://localhost:8000/health

# Logs do backend
docker compose logs api -f

# Logs do n8n
docker compose logs n8n -f

# Ver execuções no n8n
# http://localhost:5678 → Executions (menu esquerdo)
```

---

## 9. Próximo passo recomendado: Integrar Slack para handoff

No nó "Notifica equipe" de ambos os workflows, substitua o `console.log` por:

```javascript
// Nó HTTP Request para Slack
await $http.post($env.SLACK_WEBHOOK_URL, {
  text: `🚨 *Handoff solicitado*\n*Canal:* ${channel}\n*Conversa:* ${conversation_id}\n*Urgência:* ${urgency_score}\n*Intent:* ${intent}`
});
```

E adicione `SLACK_WEBHOOK_URL` nas variáveis de ambiente do n8n.
