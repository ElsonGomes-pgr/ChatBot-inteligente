/**
 * Chatbot Widget — embutir no website
 *
 * Uso:
 *   <script>
 *     window.ChatbotConfig = {
 *       n8nUrl: 'https://SEU_N8N/webhook/website-chat',
 *       title: 'Suporte',
 *       primaryColor: '#4F46E5'
 *     };
 *   </script>
 *   <script src="chatbot-widget.js"></script>
 */

(function () {
  const cfg = window.ChatbotConfig || {};
  const N8N_URL = cfg.n8nUrl || 'http://localhost:5678/webhook/website-chat';
  const TITLE = cfg.title || 'Chat';
  const COLOR = cfg.primaryColor || '#4F46E5';
  const VISITOR_ID = _getOrCreateVisitorId();

  // ── Estilos ────────────────────────────────────────────────────────────────
  const style = document.createElement('style');
  style.textContent = `
    #cb-widget * { box-sizing: border-box; font-family: system-ui, sans-serif; margin: 0; padding: 0; }
    #cb-toggle {
      position: fixed; bottom: 24px; right: 24px; z-index: 9999;
      width: 56px; height: 56px; border-radius: 50%;
      background: ${COLOR}; color: #fff; border: none; cursor: pointer;
      font-size: 24px; display: flex; align-items: center; justify-content: center;
      box-shadow: 0 4px 16px rgba(0,0,0,0.18); transition: transform .2s;
    }
    #cb-toggle:hover { transform: scale(1.08); }
    #cb-window {
      position: fixed; bottom: 92px; right: 24px; z-index: 9998;
      width: 360px; max-height: 520px;
      background: #fff; border-radius: 16px;
      box-shadow: 0 8px 32px rgba(0,0,0,0.16);
      display: flex; flex-direction: column;
      overflow: hidden; transition: opacity .2s, transform .2s;
    }
    #cb-window.cb-hidden { opacity: 0; pointer-events: none; transform: translateY(12px); }
    #cb-header {
      background: ${COLOR}; color: #fff;
      padding: 14px 16px; font-size: 15px; font-weight: 600;
      display: flex; align-items: center; justify-content: space-between;
    }
    #cb-header button { background: none; border: none; color: #fff; cursor: pointer; font-size: 18px; line-height: 1; }
    #cb-messages {
      flex: 1; overflow-y: auto; padding: 14px 12px;
      display: flex; flex-direction: column; gap: 10px;
      background: #f8f8fa;
    }
    .cb-msg { max-width: 80%; padding: 9px 13px; border-radius: 14px; font-size: 14px; line-height: 1.5; }
    .cb-msg.cb-user { background: ${COLOR}; color: #fff; align-self: flex-end; border-bottom-right-radius: 4px; }
    .cb-msg.cb-bot  { background: #fff; color: #1a1a1a; align-self: flex-start; border-bottom-left-radius: 4px; box-shadow: 0 1px 4px rgba(0,0,0,0.08); }
    .cb-msg.cb-system { background: #fff3cd; color: #856404; align-self: center; font-size: 12px; border-radius: 8px; text-align: center; padding: 6px 10px; }
    .cb-typing { display: flex; gap: 4px; align-items: center; padding: 10px 14px; background: #fff; border-radius: 14px; align-self: flex-start; box-shadow: 0 1px 4px rgba(0,0,0,0.08); }
    .cb-typing span { width: 7px; height: 7px; border-radius: 50%; background: #aaa; animation: cb-bounce .9s infinite; }
    .cb-typing span:nth-child(2) { animation-delay: .15s; }
    .cb-typing span:nth-child(3) { animation-delay: .3s; }
    @keyframes cb-bounce { 0%,60%,100%{transform:translateY(0)} 30%{transform:translateY(-5px)} }
    #cb-footer { padding: 10px 12px; background: #fff; border-top: 1px solid #eee; display: flex; gap: 8px; }
    #cb-input {
      flex: 1; border: 1px solid #e0e0e0; border-radius: 22px;
      padding: 9px 14px; font-size: 14px; outline: none;
      transition: border-color .15s;
    }
    #cb-input:focus { border-color: ${COLOR}; }
    #cb-send {
      width: 38px; height: 38px; border-radius: 50%;
      background: ${COLOR}; color: #fff; border: none; cursor: pointer;
      display: flex; align-items: center; justify-content: center; font-size: 16px;
      transition: opacity .15s;
    }
    #cb-send:disabled { opacity: .5; cursor: default; }
    @media (max-width: 420px) {
      #cb-window { width: calc(100vw - 24px); right: 12px; }
    }
  `;
  document.head.appendChild(style);

  // ── HTML ───────────────────────────────────────────────────────────────────
  const root = document.createElement('div');
  root.id = 'cb-widget';
  root.innerHTML = `
    <button id="cb-toggle" aria-label="Abrir chat">💬</button>
    <div id="cb-window" class="cb-hidden">
      <div id="cb-header">
        <span>${TITLE}</span>
        <button id="cb-close" aria-label="Fechar chat">✕</button>
      </div>
      <div id="cb-messages" role="log" aria-live="polite"></div>
      <div id="cb-footer">
        <input id="cb-input" type="text" placeholder="Digite sua mensagem..." autocomplete="off" maxlength="2000" />
        <button id="cb-send" aria-label="Enviar" disabled>➤</button>
      </div>
    </div>
  `;
  document.body.appendChild(root);

  // ── Refs ───────────────────────────────────────────────────────────────────
  const $win   = root.querySelector('#cb-window');
  const $msgs  = root.querySelector('#cb-messages');
  const $input = root.querySelector('#cb-input');
  const $send  = root.querySelector('#cb-send');
  let isOpen = false;
  let isLoading = false;
  let conversationId = null;

  // ── Toggle ─────────────────────────────────────────────────────────────────
  root.querySelector('#cb-toggle').addEventListener('click', () => {
    isOpen = !isOpen;
    $win.classList.toggle('cb-hidden', !isOpen);
    if (isOpen) {
      if ($msgs.children.length === 0) _appendBot('Olá! Como posso ajudar você hoje? 😊');
      setTimeout(() => $input.focus(), 100);
    }
  });

  root.querySelector('#cb-close').addEventListener('click', () => {
    isOpen = false;
    $win.classList.add('cb-hidden');
  });

  // ── Input ──────────────────────────────────────────────────────────────────
  $input.addEventListener('input', () => {
    $send.disabled = $input.value.trim().length === 0 || isLoading;
  });

  $input.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' && !e.shiftKey && !isLoading) _send();
  });

  $send.addEventListener('click', _send);

  // ── Core ───────────────────────────────────────────────────────────────────
  async function _send() {
    const text = $input.value.trim();
    if (!text || isLoading) return;

    _appendUser(text);
    $input.value = '';
    $send.disabled = true;
    isLoading = true;

    const typing = _showTyping();

    try {
      const res = await fetch(N8N_URL, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          visitor_id: VISITOR_ID,
          text,
          name: cfg.userName || null,
          email: cfg.userEmail || null,
          page_url: location.href,
          session_id: conversationId,
        }),
      });

      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();

      conversationId = data.conversation_id || conversationId;
      typing.remove();

      if (data.reply) _appendBot(data.reply);

      if (data.human_handoff) {
        _appendSystem(data.handoff_message || 'Um agente humano irá continuar seu atendimento.');
        $input.disabled = true;
        $send.disabled = true;
      }

    } catch (err) {
      typing.remove();
      _appendBot('Desculpe, ocorreu um erro. Tente novamente em instantes.');
      console.error('[ChatbotWidget]', err);
    } finally {
      isLoading = false;
      if (!$input.disabled) {
        $send.disabled = $input.value.trim().length === 0;
      }
    }
  }

  // ── Helpers de UI ──────────────────────────────────────────────────────────
  function _appendUser(text) {
    const el = document.createElement('div');
    el.className = 'cb-msg cb-user';
    el.textContent = text;
    $msgs.appendChild(el);
    _scrollBottom();
  }

  function _appendBot(text) {
    const el = document.createElement('div');
    el.className = 'cb-msg cb-bot';
    el.textContent = text;
    $msgs.appendChild(el);
    _scrollBottom();
  }

  function _appendSystem(text) {
    const el = document.createElement('div');
    el.className = 'cb-msg cb-system';
    el.textContent = '⚠️ ' + text;
    $msgs.appendChild(el);
    _scrollBottom();
  }

  function _showTyping() {
    const el = document.createElement('div');
    el.className = 'cb-typing';
    el.innerHTML = '<span></span><span></span><span></span>';
    $msgs.appendChild(el);
    _scrollBottom();
    return el;
  }

  function _scrollBottom() {
    $msgs.scrollTop = $msgs.scrollHeight;
  }

  // ── Visitor ID ─────────────────────────────────────────────────────────────
  function _getOrCreateVisitorId() {
    const key = 'cb_visitor_id';
    let id = localStorage.getItem(key);
    if (!id) {
      id = 'v_' + Math.random().toString(36).slice(2) + '_' + Date.now();
      localStorage.setItem(key, id);
    }
    return id;
  }
})();
