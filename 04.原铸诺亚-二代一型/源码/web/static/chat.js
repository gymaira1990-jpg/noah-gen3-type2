// ═══════════════════════════════════════════
// NOAH-PRIME · 对话界面
// 战锤40K主题: 铸造圣殿通讯终端
// ═══════════════════════════════════════════

const chatMessages = document.getElementById('chatMessages');
const userInput = document.getElementById('userInput');
const sendBtn = document.getElementById('sendBtn');
const chatStatus = document.getElementById('chatStatus');
const tokenCounter = document.getElementById('tokenCounter');
let todayTokens = 0;

// WebSocket
let ws = null;
function connectWS() {
  const proto = location.protocol === 'https:' ? 'wss:' : 'ws:';
  ws = new WebSocket(`${proto}//${location.host}/chat`);

  ws.onopen = () => chatStatus.textContent = '◆ 星语庭已连接';
  ws.onmessage = (e) => {
    const data = JSON.parse(e.data);
    if (data.type === 'status') {
      chatStatus.textContent = data.content;
    } else if (data.type === 'chunk') {
      appendChunk(data.content);
    } else if (data.type === 'done') {
      finalizeMessage(data.tokens_used || 0);
    }
  };
  ws.onclose = () => { chatStatus.textContent = '◆ 星语庭静默 · 3秒后重连'; setTimeout(connectWS, 3000); };
  ws.onerror = () => { chatStatus.textContent = '◆ 通讯干扰'; };
}

let currentNoahMsg = null;
function appendChunk(text) {
  if (!currentNoahMsg) {
    currentNoahMsg = addMessage('noah', '');
  }
  currentNoahMsg.textContent += text;
  chatMessages.scrollTop = chatMessages.scrollHeight;
}

function finalizeMessage(tokens) {
  todayTokens += tokens;
  tokenCounter.textContent = `今日Token: ${todayTokens}`;
  currentNoahMsg = null;
  chatStatus.textContent = '◆ 就绪';
}

function addMessage(role, text) {
  const div = document.createElement('div');
  div.className = `message ${role}`;
  div.textContent = text;
  chatMessages.appendChild(div);
  chatMessages.scrollTop = chatMessages.scrollHeight;
  return div;
}

// HTTP fallback
async function sendHTTP(msg) {
  chatStatus.textContent = '⚙ 大贤者思考中...';
  try {
    const resp = await fetch('/api/chat', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ message: msg }),
    });
    const data = await resp.json();
    if (data.reply) {
      addMessage('noah', data.reply);
      todayTokens += data.tokens_used || 0;
      tokenCounter.textContent = `今日Token: ${todayTokens}`;
    }
    chatStatus.textContent = '◆ 就绪';
  } catch (e) {
    addMessage('noah', '铸造圣殿通讯中断——请稍后再试');
    chatStatus.textContent = '◆ 通讯失败';
  }
}

// Send
function send() {
  const text = userInput.value.trim();
  if (!text) return;
  addMessage('user', text);
  userInput.value = '';

  if (ws && ws.readyState === WebSocket.OPEN) {
    ws.send(text);
  } else {
    sendHTTP(text);
  }
}

sendBtn.addEventListener('click', send);
userInput.addEventListener('keydown', (e) => {
  if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); send(); }
});

connectWS();
