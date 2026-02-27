/**
 * Symphony Concierge — Chat UI
 * Talks to Ollama running locally on port 11434 via the /api/chat endpoint.
 * Zero external dependencies — vanilla JS only.
 */

'use strict';

// ─── Config ───────────────────────────────────────────────────────────────────

const OLLAMA_URL   = '/api/chat';   // Proxied through Nginx to localhost:11434
const MODEL_NAME   = window.CONCIERGE_MODEL || 'symphony-home:latest';
const MAX_MESSAGES = 40;           // Keep last 40 messages in history

// ─── State ────────────────────────────────────────────────────────────────────

const state = {
  messages: [],   // { role: 'user'|'assistant', content: string }
  isThinking: false,
};

// ─── DOM helpers ──────────────────────────────────────────────────────────────

const chatLog    = document.getElementById('chat-log');
const inputField = document.getElementById('message-input');
const sendBtn    = document.getElementById('send-btn');
const statusDot  = document.getElementById('status-dot');
const statusText = document.getElementById('status-text');

function scrollToBottom() {
  chatLog.scrollTop = chatLog.scrollHeight;
}

function setStatus(connected) {
  statusDot.className  = connected ? 'dot dot-green' : 'dot dot-red';
  statusText.textContent = connected ? 'Online' : 'Offline';
}

function stripMarkdown(text) {
  return text
    .replace(/\*\*(.+?)\*\*/g, '$1')  // bold
    .replace(/\*(.+?)\*/g,   '$1')   // italic
    .replace(/`(.+?)`/g,     '$1')   // inline code
    .replace(/#{1,6}\s+/g,   '')     // headings
    .replace(/^-\s+/gm,      '')     // list items
    .replace(/\n{3,}/g,      '\n\n') // collapse blank lines
    .trim();
}

function appendMessage(role, content) {
  const wrap = document.createElement('div');
  wrap.classList.add('message', role === 'user' ? 'msg-user' : 'msg-assistant');

  const bubble = document.createElement('div');
  bubble.classList.add('bubble');
  bubble.textContent = stripMarkdown(content);

  wrap.appendChild(bubble);
  chatLog.appendChild(wrap);
  scrollToBottom();
  return bubble;
}

function showThinkingIndicator() {
  const wrap = document.createElement('div');
  wrap.classList.add('message', 'msg-assistant');
  wrap.id = 'thinking';

  const bubble = document.createElement('div');
  bubble.classList.add('bubble', 'thinking');
  bubble.innerHTML = '<span></span><span></span><span></span>';

  wrap.appendChild(bubble);
  chatLog.appendChild(wrap);
  scrollToBottom();
}

function removeThinkingIndicator() {
  document.getElementById('thinking')?.remove();
}

// ─── Ollama streaming chat ────────────────────────────────────────────────────

async function sendMessage(userText) {
  if (state.isThinking || !userText.trim()) return;

  state.isThinking = true;
  sendBtn.disabled = true;
  inputField.value = '';

  // Add user message to history and DOM
  state.messages.push({ role: 'user', content: userText });
  if (state.messages.length > MAX_MESSAGES) state.messages.shift();
  appendMessage('user', userText);
  showThinkingIndicator();

  try {
    const res = await fetch(OLLAMA_URL, {
      method:  'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        model:    MODEL_NAME,
        messages: state.messages,
        stream:   true,
      }),
    });

    if (!res.ok) throw new Error(`HTTP ${res.status}`);

    removeThinkingIndicator();
    const assistantBubble = appendMessage('assistant', '');
    let fullResponse = '';

    const reader = res.body.getReader();
    const decoder = new TextDecoder();

    while (true) {
      const { value, done } = await reader.read();
      if (done) break;

      const lines = decoder.decode(value).split('\n').filter(Boolean);
      for (const line of lines) {
        try {
          const chunk = JSON.parse(line);
          if (chunk.message?.content) {
            fullResponse += chunk.message.content;
            assistantBubble.textContent = stripMarkdown(fullResponse);
            scrollToBottom();
          }
        } catch { /* skip malformed chunks */ }
      }
    }

    // Save to history
    state.messages.push({ role: 'assistant', content: fullResponse });
    if (state.messages.length > MAX_MESSAGES) state.messages.shift();
    setStatus(true);

  } catch (err) {
    removeThinkingIndicator();
    appendMessage('assistant', 'I\'m having a technical difficulty. Please try again or call Symphony at (303) 555-0100.');
    setStatus(false);
    console.error('[concierge] Error:', err);
  } finally {
    state.isThinking = false;
    sendBtn.disabled = false;
    inputField.focus();
  }
}

// ─── Event listeners ──────────────────────────────────────────────────────────

sendBtn.addEventListener('click', () => sendMessage(inputField.value));

inputField.addEventListener('keydown', (e) => {
  if (e.key === 'Enter' && !e.shiftKey) {
    e.preventDefault();
    sendMessage(inputField.value);
  }
});

// ─── Init ─────────────────────────────────────────────────────────────────────

(async function init() {
  try {
    const r = await fetch('/api/tags', { method: 'GET' });
    setStatus(r.ok);
  } catch {
    setStatus(false);
  }

  // Welcome message
  appendMessage('assistant', 'Hello! I\'m Symphony Concierge, your home assistant. How can I help you today?');
  inputField.focus();
})();
