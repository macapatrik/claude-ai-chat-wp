(function () {
  'use strict';

  const d = caicwData;
  let isOpen = false;
  let messages = [];
  let visitor = { name: '', email: '' };
  let started = false;

  /* ── Build UI ──────────────────────────────────────────── */
  const root = document.getElementById('caicw-root');
  if (!root) return;

  root.innerHTML = `
    <button id="caicw-toggle" aria-label="Open chat" aria-expanded="false">
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/></svg>
      <span id="caicw-badge" style="display:none">1</span>
    </button>

    <div id="caicw-window" role="dialog" aria-modal="true" aria-label="${d.widgetTitle}" style="display:none">
      <div id="caicw-header">
        <span id="caicw-title">${d.widgetTitle}</span>
        <button id="caicw-close" aria-label="Close chat">✕</button>
      </div>

      <div id="caicw-body">
        <div id="caicw-messages" role="log" aria-label="Chat messages"></div>

        <div id="caicw-intake">
          <p>${d.welcomeMsg}</p>
          <input id="caicw-name"  type="text"  placeholder="${d.namePlaceholder}"  autocomplete="name" />
          <input id="caicw-email" type="email" placeholder="${d.emailPlaceholder}" autocomplete="email" />
          <button id="caicw-start">${d.startBtn}</button>
        </div>

        <div id="caicw-composer" style="display:none">
          <textarea id="caicw-input" rows="2" placeholder="${d.placeholder}" aria-label="Message input"></textarea>
          <button id="caicw-send" aria-label="Send message">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="22" y1="2" x2="11" y2="13"/><polygon points="22 2 15 22 11 13 2 9 22 2"/></svg>
          </button>
        </div>
      </div>
    </div>
  `;

  /* ── Apply accent color ────────────────────────────────── */
  const r = root.style;
  document.documentElement.style.setProperty('--caicw-accent', d.accentColor);

  /* ── Helpers ───────────────────────────────────────────── */
  function openChat() {
    isOpen = true;
    document.getElementById('caicw-window').style.display = 'flex';
    document.getElementById('caicw-toggle').setAttribute('aria-expanded', 'true');
    document.getElementById('caicw-badge').style.display = 'none';
  }

  function closeChat() {
    isOpen = false;
    document.getElementById('caicw-window').style.display = 'none';
    document.getElementById('caicw-toggle').setAttribute('aria-expanded', 'false');
  }

  function addMessage(role, text) {
    const log = document.getElementById('caicw-messages');
    const el  = document.createElement('div');
    el.className = 'caicw-msg caicw-msg--' + role;
    el.setAttribute('role', role === 'assistant' ? 'status' : '');
    el.textContent = text;
    log.appendChild(el);
    log.scrollTop = log.scrollHeight;
  }

  function setLoading(on) {
    const btn = document.getElementById('caicw-send');
    btn.disabled = on;
    btn.classList.toggle('caicw-loading', on);
  }

  async function sendMessage(userText) {
    if (!userText.trim()) return;

    messages.push({ role: 'user', content: userText });
    addMessage('user', userText);
    document.getElementById('caicw-input').value = '';
    setLoading(true);

    const formData = new FormData();
    formData.append('action',       'caicw_chat');
    formData.append('nonce',        d.nonce);
    formData.append('visitor_name', visitor.name);
    formData.append('visitor_email',visitor.email);
    messages.forEach((m, i) => {
      formData.append(`messages[${i}][role]`,    m.role);
      formData.append(`messages[${i}][content]`, m.content);
    });

    try {
      const res  = await fetch(d.ajaxUrl, { method: 'POST', body: formData });
      const json = await res.json();

      if (json.success) {
        const reply = json.data.reply;
        const cleanReply = reply.replace(/\[ESCALATE\]\[[^\]]*\]/g, '').trim();
        messages.push({ role: 'assistant', content: reply });
        addMessage('assistant', cleanReply);

        if (json.data.escalated) {
          addMessage('system', d.escalatedMsg);
        }
      } else {
        addMessage('system', d.errorMsg);
      }
    } catch (e) {
      addMessage('system', d.errorMsg);
    } finally {
      setLoading(false);
    }
  }

  /* ── Events ────────────────────────────────────────────── */
  document.getElementById('caicw-toggle').addEventListener('click', () => isOpen ? closeChat() : openChat());
  document.getElementById('caicw-close').addEventListener('click', closeChat);

  document.getElementById('caicw-start').addEventListener('click', () => {
    const name  = document.getElementById('caicw-name').value.trim();
    const email = document.getElementById('caicw-email').value.trim();

    if (!name) { document.getElementById('caicw-name').focus(); return; }

    visitor = { name, email };
    started = true;

    document.getElementById('caicw-intake').style.display   = 'none';
    document.getElementById('caicw-composer').style.display = 'flex';
    document.getElementById('caicw-input').focus();

    addMessage('assistant', `Hi ${name}! ${d.welcomeMsg}`);
  });

  document.getElementById('caicw-send').addEventListener('click', () => {
    sendMessage(document.getElementById('caicw-input').value);
  });

  document.getElementById('caicw-input').addEventListener('keydown', (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      sendMessage(e.target.value);
    }
  });

  /* Keyboard: close on Escape */
  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape' && isOpen) closeChat();
  });

})();
