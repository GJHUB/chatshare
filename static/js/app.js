// ── State ──────────────────────────────────────────────────────────────────
const token = localStorage.getItem('token');
const user = JSON.parse(localStorage.getItem('user') || '{}');
let currentConvId = null;
let currentModel = localStorage.getItem('model') || 'claude-opus-4';
let currentModelName = localStorage.getItem('modelName') || 'Claude Opus 4';
let isStreaming = false;
let abortController = null;
let conversations = [];
let currentMessages = []; // track messages with seq for edit/retry
let pendingFiles = []; // files waiting to be uploaded

if (!token) { window.location.href = '/login'; }

// ── marked config ──────────────────────────────────────────────────────────
marked.setOptions({ breaks: true, gfm: true });

const renderer = new marked.Renderer();
renderer.code = function(code, lang) {
  const language = lang && hljs.getLanguage(lang) ? lang : 'plaintext';
  let highlighted;
  try { highlighted = hljs.highlight(code, { language }).value; }
  catch(e) { highlighted = escapeHtml(code); }
  return `<div class="code-block-wrap">
    <div class="code-header">
      <span>${language}</span>
      <button class="copy-code-btn" onclick="copyCode(this)">复制</button>
    </div>
    <pre><code class="hljs language-${language}">${highlighted}</code></pre>
  </div>`;
};
marked.use({ renderer });

// ── API helper ─────────────────────────────────────────────────────────────
async function api(method, path, body) {
  const opts = {
    method,
    headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${token}` }
  };
  if (body !== undefined) opts.body = JSON.stringify(body);
  const res = await fetch(path, opts);
  if (res.status === 401) { logout(); return null; }
  return res;
}

// ── Init ───────────────────────────────────────────────────────────────────
async function init() {
  initTheme();
  document.getElementById('user-name').textContent = user.nickname || user.username || '用户';
  document.getElementById('user-avatar').textContent = (user.nickname || user.username || 'U')[0].toUpperCase();
  document.getElementById('model-name-display').textContent = currentModelName;
  await loadModels();
  await loadConversations();
}


function welcomeTemplate() {
  return `<div class="welcome" id="welcome">
    <div class="welcome-icon">🍲</div>
    <h2>有什么可以帮你的？</h2>
    <p>选择模型，开始你的 AI 之旅</p>
    <div class="quick-prompts">
      <div class="quick-prompt-card" data-prompt="帮我写一个 Python 脚本来整理日志文件">
        <div class="icon">💡</div><div class="title">写代码</div><div class="desc">帮我写一个 Python 脚本</div>
      </div>
      <div class="quick-prompt-card" data-prompt="帮我写一篇关于 AI 代理设计的短文">
        <div class="icon">📝</div><div class="title">写文章</div><div class="desc">帮我写一篇关于AI的短文</div>
      </div>
      <div class="quick-prompt-card" data-prompt="生成一张未来城市夜景图片">
        <div class="icon">🎨</div><div class="title">画图片</div><div class="desc">生成一张未来城市夜景</div>
      </div>
    </div>
  </div>`;
}

function bindWelcomePrompts() {
  document.querySelectorAll('.quick-prompt-card').forEach(card => {
    card.onclick = () => {
      const text = card.dataset.prompt || '';
      const input = document.getElementById('msg-input');
      input.value = text;
      input.dispatchEvent(new Event('input'));
      input.focus();
    };
  });
}

function isImageVideoModel(id) {
  const mids = ['4o-image','Nano-banana','Nano-banana-Pro','即梦-4.0画图模型','即梦-4.1画图模型','即梦-4.5画图模型','Veo_3_1','即梦3.0视频模型'];
  return mids.includes(id);
}


function initTheme() {
  const theme = localStorage.getItem('theme') || 'light';
  document.documentElement.setAttribute('data-theme', theme);
  updateThemeIcon(theme);
}

function toggleTheme() {
  const current = document.documentElement.getAttribute('data-theme') || 'light';
  const next = current === 'dark' ? 'light' : 'dark';
  document.documentElement.setAttribute('data-theme', next);
  localStorage.setItem('theme', next);
  updateThemeIcon(next);
}

function updateThemeIcon(theme) {
  const btn = document.getElementById('theme-toggle');
  if (!btn) return;
  btn.textContent = theme === 'dark' ? '☀️' : '🌙';
  btn.title = theme === 'dark' ? '切换到白色主题' : '切换到深色主题';
}

// ── Models ─────────────────────────────────────────────────────────────────
async function loadModels() {
  try {
    const res = await api('GET', '/api/models');
    if (!res || !res.ok) { renderModelDropdown(staticModelGroups()); return; }
    const groups = await res.json();
    renderModelDropdown(groups);
  } catch(e) { renderModelDropdown(staticModelGroups()); }
}

function staticModelGroups() {
  return [
    { group: 'GPT 系列', models: [
      {id:'gpt-5-2',name:'GPT-5.2'},{id:'gpt-5-2-instant',name:'GPT-5.2 Instant'},
      {id:'gpt-5-2-thinking',name:'GPT-5.2 Thinking'},{id:'gpt-5-2-pro',name:'GPT-5.2 Pro'},
      {id:'gpt-5-1',name:'GPT-5.1'},{id:'gpt-5-1-thinking',name:'GPT-5.1 Thinking'},
      {id:'gpt-5-1-pro',name:'GPT-5.1 Pro'}
    ]},
    { group: 'Claude 系列', models: [
      {id:'claude-opus-4',name:'Claude Opus 4'},{id:'claude-4.6-sonnet',name:'Claude 4.6 Sonnet'},
      {id:'claude-4.6-sonnet-code',name:'Claude 4.6 Sonnet (编程)'},{id:'claude-code',name:'Claude Code'}
    ]},
    { group: 'Gemini 系列', models: [
      {id:'gemini-pro',name:'Gemini 3.1 Pro [API]'},{id:'gemini-pro-web',name:'Gemini 3.1 Pro [联网]'},
      {id:'gemini-flash',name:'Gemini 3.1 Flash'}
    ]},
    { group: 'Grok 系列', models: [
      {id:'grok-4',name:'Grok 4'},{id:'grok-4.2',name:'Grok 4.2'},
      {id:'grok-4.2-thinking',name:'Grok 4.2 Thinking'},{id:'grok-4-research',name:'Grok 4 深度研究'},
      {id:'grok-3',name:'Grok 3'}
    ]},
    { group: 'Deepseek 系列', models: [
      {id:'deepseek-v3',name:'Deepseek V3'},{id:'deepseek-r1',name:'Deepseek R1'}
    ]},
    { group: '图片生成模型', models: [
      {id:'4o-image',name:'4o-image'},{id:'Nano-banana',name:'Nano-banana'},{id:'Nano-banana-Pro',name:'Nano-banana-Pro'},
      {id:'即梦-4.0画图模型',name:'即梦 4.0 画图'},{id:'即梦-4.1画图模型',name:'即梦 4.1 画图'},{id:'即梦-4.5画图模型',name:'即梦 4.5 画图'}
    ]},
    { group: '视频生成模型', models: [
      {id:'Veo_3_1',name:'Veo 3.1'},{id:'即梦3.0视频模型',name:'即梦 3.0 视频'}
    ]},
    { group: 'Codex 编程系列', models: [
      {id:'codex-5.2',name:'GPT-5.2 Codex'},{id:'codex-5.2-max',name:'GPT-5.2 Codex Max'},
      {id:'codex-5.3',name:'GPT-5.3 Codex'}
    ]}
  ];
}

function renderModelDropdown(groups) {
  const dd = document.getElementById('model-dropdown');
  dd.innerHTML = '';
  for (const g of groups) {
    const hdr = document.createElement('div');
    hdr.className = 'model-group-header';
    hdr.textContent = g.group;
    dd.appendChild(hdr);
    for (const m of g.models) {
      const item = document.createElement('div');
      item.className = 'model-item' + (m.id === currentModel ? ' active' : '') + (m.disabled ? ' disabled' : '');
      item.textContent = m.name + (m.disabled ? ' (即将支持)' : '');
      item.dataset.id = m.id;
      item.dataset.name = m.name;
      if (!m.disabled) {
        item.onclick = () => selectModel(m.id, m.name);
      } else {
        item.style.opacity = '0.4';
        item.style.cursor = 'not-allowed';
      }
      dd.appendChild(item);
    }
  }
}

function selectModel(id, name) {
  currentModel = id; currentModelName = name;
  localStorage.setItem('model', id);
  localStorage.setItem('modelName', name);
  document.getElementById('model-name-display').textContent = name;
  document.getElementById('model-dropdown').style.display = 'none';
  document.querySelectorAll('.model-item').forEach(el => el.classList.toggle('active', el.dataset.id === id));
}

function toggleModelDropdown(e) {
  e.stopPropagation();
  const dd = document.getElementById('model-dropdown');
  dd.style.display = dd.style.display === 'none' ? 'block' : 'none';
}

// ── Conversations ──────────────────────────────────────────────────────────
async function loadConversations() {
  const res = await api('GET', '/api/conversations');
  if (!res || !res.ok) return;
  conversations = await res.json();
  renderConversations();
}

function renderConversations() {
  const list = document.getElementById('conv-list');
  const q = document.getElementById('search-input').value.toLowerCase();
  list.innerHTML = '';
  for (const conv of conversations) {
    if (q && !conv.title.toLowerCase().includes(q)) continue;
    const item = document.createElement('div');
    item.className = 'conv-item' + (conv.id === currentConvId ? ' active' : '');
    item.dataset.id = conv.id;
    item.innerHTML = `
      <span class="conv-title" data-id="${conv.id}">${escapeHtml(conv.title || '新对话')}</span>
      <div class="conv-actions">
        <button class="conv-action-btn" onclick="startRenameConv(event,${conv.id})" title="重命名">✏️</button>
        <button class="conv-action-btn" onclick="deleteConv(event,${conv.id})" title="删除">🗑️</button>
      </div>`;
    item.addEventListener('click', e => { if (!e.target.closest('.conv-actions') && !e.target.classList.contains('conv-rename-input')) loadConversation(conv.id); });
    // Double-click to rename
    const titleSpan = item.querySelector('.conv-title');
    titleSpan.addEventListener('dblclick', e => { e.stopPropagation(); startInlineRename(conv.id, titleSpan); });
    list.appendChild(item);
  }
}

function startInlineRename(convId, titleSpan) {
  const conv = conversations.find(c => c.id === convId);
  if (!conv) return;
  const input = document.createElement('input');
  input.type = 'text';
  input.className = 'conv-rename-input';
  input.value = conv.title;
  input.onclick = e => e.stopPropagation();
  input.onkeydown = async e => {
    if (e.key === 'Enter') { await finishRename(convId, input.value); }
    if (e.key === 'Escape') { renderConversations(); }
  };
  input.onblur = async () => { await finishRename(convId, input.value); };
  titleSpan.replaceWith(input);
  input.focus();
  input.select();
}

async function finishRename(convId, newTitle) {
  newTitle = newTitle.trim();
  const conv = conversations.find(c => c.id === convId);
  if (!newTitle || !conv || newTitle === conv.title) { renderConversations(); return; }
  const res = await api('PUT', `/api/conversations/${convId}`, { title: newTitle });
  if (res && res.ok) { conv.title = newTitle; }
  renderConversations();
}

async function startRenameConv(e, convId) {
  e.stopPropagation();
  const item = e.target.closest('.conv-item');
  const titleSpan = item.querySelector('.conv-title');
  startInlineRename(convId, titleSpan);
}

async function loadConversation(convId) {
  currentConvId = convId;
  renderConversations();
  const res = await api('GET', `/api/conversations/${convId}/messages`);
  if (!res || !res.ok) return;
  const msgs = await res.json();
  currentMessages = msgs;
  const el = document.getElementById('messages');
  el.innerHTML = '';
  for (const m of msgs) appendMessage(m.role, m.content, false, m.seq, m.model);
  scrollToBottom();
}

async function newConversation() {
  currentConvId = null;
  currentMessages = [];
  document.getElementById('messages').innerHTML = welcomeTemplate();
  bindWelcomePrompts();
  renderConversations();
  document.getElementById('msg-input').focus();
  closeSidebar();
}

async function deleteConv(e, convId) {
  e.stopPropagation();
  if (!confirm('确定删除这个对话？')) return;
  const res = await api('DELETE', `/api/conversations/${convId}`);
  if (res && res.ok) {
    conversations = conversations.filter(c => c.id !== convId);
    if (currentConvId === convId) newConversation();
    renderConversations();
  }
}

// ── Messaging ──────────────────────────────────────────────────────────────
// ── File upload ────────────────────────────────────────────────────────────
function toggleUploadMenu() {
  const menu = document.getElementById('upload-menu');
  menu.classList.toggle('hidden');
}

function openFileSelector() {
  const input = document.createElement('input');
  input.type = 'file';
  input.multiple = true;
  input.accept = '.txt,.md,.csv,.json,.xml,.pdf,.docx,.pptx,.xlsx,.py,.js,.java,.c,.cpp,.jpg,.jpeg,.png,.gif,.webp';
  input.onchange = (e) => handleFilesSelected(e.target.files);
  input.click();
  toggleUploadMenu();
}

function handleFilesSelected(files) {
  for (const file of files) {
    if (pendingFiles.length >= 5) { alert('最多同时上传 5 个文件'); break; }
    pendingFiles.push(file);
  }
  renderFilePreview();
}

function renderFilePreview() {
  const container = document.getElementById('file-preview-area');
  container.innerHTML = '';
  if (pendingFiles.length === 0) { container.classList.add('hidden'); return; }
  container.classList.remove('hidden');
  pendingFiles.forEach((file, idx) => {
    const item = document.createElement('div');
    item.className = 'file-preview-item';
    item.id = `file-preview-${idx}`;
    const isImage = file.type.startsWith('image/');
    const icon = isImage ? '🖼️' : '📄';
    const size = formatFileSize(file.size);
    let html = '';
    if (isImage) {
      html += `<img class="file-thumbnail" src="${URL.createObjectURL(file)}">`;
    }
    html += `<span class="file-info">${icon} ${file.name} (${size})</span>`;
    html += `<span class="file-remove" onclick="removeFile(${idx})">✕</span>`;
    item.innerHTML = html;
    container.appendChild(item);
  });
}

function removeFile(idx) {
  pendingFiles.splice(idx, 1);
  renderFilePreview();
}

function formatFileSize(bytes) {
  if (bytes < 1024) return bytes + ' B';
  if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB';
  return (bytes / (1024 * 1024)).toFixed(1) + ' MB';
}

function showUploadProgress(idx, pct) {
  const item = document.getElementById(`file-preview-${idx}`);
  if (!item) return;
  let bar = item.querySelector('.file-progress');
  if (!bar) {
    bar = document.createElement('div');
    bar.className = 'file-progress';
    bar.innerHTML = '<div class="file-progress-bar" style="width:0%"></div>';
    item.appendChild(bar);
  }
  bar.querySelector('.file-progress-bar').style.width = pct + '%';
}

async function fetchWithRetry(url, options, retries = 1) {
  let lastErr;
  for (let i = 0; i <= retries; i++) {
    try {
      const resp = await fetch(url, options);
      if (resp.ok || i === retries) return resp;
      lastErr = new Error(`HTTP ${resp.status}`);
    } catch (e) {
      lastErr = e;
      if (i === retries) throw e;
    }
  }
  throw lastErr;
}

function pickField(obj, keys) {
  for (const k of keys) {
    if (obj && obj[k] !== undefined && obj[k] !== null && obj[k] !== '') return obj[k];
  }
  return null;
}

async function getImageDimensions(file) {
  return new Promise((resolve) => {
    try {
      const url = URL.createObjectURL(file);
      const img = new Image();
      img.onload = () => {
        const width = img.naturalWidth || 0;
        const height = img.naturalHeight || 0;
        URL.revokeObjectURL(url);
        resolve({ width, height });
      };
      img.onerror = () => {
        URL.revokeObjectURL(url);
        resolve({ width: 0, height: 0 });
      };
      img.src = url;
    } catch (_) {
      resolve({ width: 0, height: 0 });
    }
  });
}

async function uploadPendingFiles() {
  const attachments = [];
  for (let i = 0; i < pendingFiles.length; i++) {
    const file = pendingFiles[i];
    showUploadProgress(i, 10);

    try {
      // Stage 1: register file (JSON metadata, align with official HAR)
      const registerResp = await fetchWithRetry('/backend-api/files', {
        method: 'POST',
        headers: {
          'Authorization': `Bearer ${token}`,
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          file_name: file.name,
          file_size: file.size,
          use_case: 'multimodal',
          timezone_offset_min: -480,
          reset_rate_limits: false,
          mime_type: file.type || 'application/octet-stream',
        }),
      }, 1);

      if (!registerResp.ok) {
        const err = await registerResp.text().catch(() => '');
        alert(`文件 ${file.name} 登记失败: ${registerResp.status} ${err}`);
        continue;
      }

      const result = await registerResp.json();
      const fileId = pickField(result, ['id', 'file_id']);
      if (!fileId) {
        alert(`文件 ${file.name} 上传失败：未返回 file_id`);
        continue;
      }

      // Stage 2: object upload (optional)
      const uploadUrl = pickField(result, ['upload_proxy_url', 'upload_url', 'uploadUrl']);
      if (uploadUrl) {
        showUploadProgress(i, 45);
        let uploadPath = uploadUrl;
        try {
          const u = new URL(uploadUrl, window.location.origin);
          uploadPath = u.pathname + (u.search || '');
        } catch (_) {
          // keep original when not absolute URL
        }
        const uploadResp = await fetchWithRetry(uploadPath, {
          method: 'PUT',
          headers: {
            'Authorization': `Bearer ${token}`,
            'Content-Type': 'application/octet-stream',
          },
          body: file,
        }, 1);
        const uploadText = await uploadResp.text().catch(() => '');
        const uploadBad = /unauthorized|\"error\"|\"detail\"\s*:\s*\"unauthorized\"/i.test(uploadText || '');
        if (!uploadResp.ok || uploadBad) {
          alert(`文件 ${file.name} 对象上传失败: ${uploadResp.status}${uploadBad ? ' (Unauthorized)' : ''}`);
          continue;
        }
      }

      // Stage 3: process stream confirm
      showUploadProgress(i, 75);
      const processResp = await fetchWithRetry('/backend-api/files/process_upload_stream', {
        method: 'POST',
        headers: {
          'Authorization': `Bearer ${token}`,
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          file_id: fileId,
          use_case: 'multimodal',
          index_for_retrieval: false,
          file_name: file.name,
          context_scopes: ['GLOBAL'],
        }),
      }, 1);
      if (!processResp.ok) {
        alert(`文件 ${file.name} 上传确认失败: ${processResp.status}`);
        continue;
      }

      showUploadProgress(i, 100);
      const mime = pickField(result, ['mime_type', 'mimeType']) || file.type || 'application/octet-stream';
      const dims = mime.startsWith('image/') ? await getImageDimensions(file) : { width: 0, height: 0 };
      attachments.push({
        id: fileId,
        mime_type: mime,
        name: pickField(result, ['name', 'filename']) || file.name,
        size_bytes: Number(pickField(result, ['size_bytes', 'sizeBytes'])) || file.size,
        width: dims.width,
        height: dims.height,
        preview_url: mime.startsWith('image/') ? URL.createObjectURL(file) : null,
      });
    } catch (e) {
      alert(`文件 ${file.name} 上传出错: ${e.message}`);
    }
  }
  pendingFiles = [];
  return attachments;
}

// Close upload menu on click outside / ESC
document.addEventListener('click', (e) => {
  const menu = document.getElementById('upload-menu');
  if (menu && !menu.classList.contains('hidden') && !e.target.closest('.attach-wrap')) {
    menu.classList.add('hidden');
  }
});
document.addEventListener('keydown', (e) => {
  if (e.key === 'Escape') {
    const menu = document.getElementById('upload-menu');
    if (menu) menu.classList.add('hidden');
  }
});

// ── Send message ──────────────────────────────────────────────────────────
async function sendMessage() {
  if (isStreaming) { stopGeneration(); return; }
  const input = document.getElementById('msg-input');
  const content = input.value.trim();
  if (!content && pendingFiles.length === 0) return;

  // Upload files first if any
  let attachments = [];
  const hadFiles = pendingFiles.length > 0;
  if (hadFiles) {
    attachments = await uploadPendingFiles();
    document.getElementById('file-preview-area').innerHTML = '';
    document.getElementById('file-preview-area').classList.add('hidden');
    if (attachments.length === 0) {
      alert('文件上传未成功，已中断本次发送');
      return;
    }
  }

  if (isImageVideoModel(currentModel) && currentConvId) {
    await newConversation();
  }

  if (!currentConvId) {
    const res = await api('POST', '/api/conversations', { model: currentModel });
    if (!res || !res.ok) return;
    const conv = await res.json();
    conversations.unshift(conv);
    currentConvId = conv.id;
    renderConversations();
  }

  input.value = ''; input.style.height = 'auto';
  const welcomeEl = document.getElementById('welcome');
  if (welcomeEl) welcomeEl.style.display = 'none';

  const displayContent = content || '📎 [文件已上传]';
  appendMessage('user', displayContent, false, null, null, attachments);
  const aiWrap = appendMessage('assistant', '', true, null, null);
  scrollToBottom();

  const body = { content: content || '请分析上传的文件', model: currentModel };
  if (attachments.length > 0) {
    // only keep ChatShare-accepted fields
    body.attachments = attachments.map(a => ({
      id: a.id,
      mime_type: a.mime_type,
      name: a.name,
      size_bytes: Number(a.size_bytes) || 0,
      width: Number(a.width) || 0,
      height: Number(a.height) || 0,
    }));
    body.force_new_chatshare_context = true;
  }

  await streamResponse(`/api/conversations/${currentConvId}/messages`, 'POST', body, aiWrap);
}

async function streamResponse(url, method, body, aiWrap) {
  isStreaming = true; updateSendBtn();
  abortController = new AbortController();
  let fullText = '';

  try {
    const res = await fetch(url, {
      method,
      headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${token}` },
      body: JSON.stringify(body),
      signal: abortController.signal
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      setMsgContent(aiWrap, `❌ ${err.detail || '请求失败'}`, false);
      return;
    }
    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let buf = '';
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buf += decoder.decode(value, { stream: true });
      const lines = buf.split('\n');
      buf = lines.pop();
      for (const line of lines) {
        if (!line.startsWith('data: ')) continue;
        const raw = line.slice(6).trim();
        if (raw === '[DONE]') continue;
        try {
          const chunk = JSON.parse(raw);
          if (chunk.error) { setMsgContent(aiWrap, `❌ ${chunk.error}`, false); return; }
          const delta = chunk.choices?.[0]?.delta?.content;
          if (delta) { fullText += delta; setMsgContent(aiWrap, fullText, true); }
        } catch(e) {}
      }
    }
    if (fullText) setMsgContent(aiWrap, fullText, false);
    // Reload current conversation messages to get updated seq numbers
    if (currentConvId) {
      const msgRes = await api('GET', `/api/conversations/${currentConvId}/messages`);
      if (msgRes && msgRes.ok) {
        currentMessages = await msgRes.json();
        // Update aiWrap's data-seq from the latest assistant message
        if (aiWrap && currentMessages.length > 0) {
          const lastAssistant = [...currentMessages].reverse().find(m => m.role === 'assistant' && !m.replaced);
          if (lastAssistant) {
            aiWrap.dataset.seq = lastAssistant.seq;
            const retryMenu = aiWrap.querySelector('.retry-menu');
            if (retryMenu) {
              retryMenu.dataset.seq = lastAssistant.seq;
              const s = lastAssistant.seq;
              retryMenu.querySelectorAll('.retry-menu-item').forEach(item => {
                const onclick = item.getAttribute('onclick');
                if (onclick) item.setAttribute('onclick', onclick.replace(/\d+/g, s));
              });
            }
          }
        }
      }
    }
  } catch(e) {
    if (e.name !== 'AbortError') setMsgContent(aiWrap, '❌ 连接错误，请重试', false);
    else if (fullText) setMsgContent(aiWrap, fullText, false);
  } finally {
    isStreaming = false; updateSendBtn(); abortController = null; scrollToBottom();
  }
}

function stopGeneration() {
  if (abortController) abortController.abort();
}

// ── Edit message ───────────────────────────────────────────────────────────
function startEditMessage(seq, wrap) {
  const msg = currentMessages.find(m => m.seq === seq && m.role === 'user');
  if (!msg) return;
  const contentDiv = wrap.querySelector('.msg-content');
  const editActions = wrap.querySelector('.msg-edit-actions');
  const originalContent = msg.content;

  contentDiv.innerHTML = '';
  const textarea = document.createElement('textarea');
  textarea.className = 'edit-textarea';
  textarea.value = originalContent;
  textarea.rows = Math.min(originalContent.split('\n').length + 1, 10);
  contentDiv.appendChild(textarea);

  const btnWrap = document.createElement('div');
  btnWrap.className = 'edit-btn-wrap';
  btnWrap.innerHTML = `<button class="edit-save-btn" onclick="saveEditMessage(${seq}, this)">保存并提交</button>
    <button class="edit-cancel-btn" onclick="cancelEditMessage(${seq}, this)">取消</button>`;
  contentDiv.appendChild(btnWrap);
  if (editActions) editActions.style.display = 'none';
  textarea.focus();
}

async function saveEditMessage(seq, btn) {
  const wrap = btn.closest('.msg-wrap');
  const textarea = wrap.querySelector('.edit-textarea');
  const content = textarea.value.trim();
  if (!content || !currentConvId) return;

  // Remove all messages from this seq onward in the DOM
  const allWraps = document.querySelectorAll('.msg-wrap');
  let found = false;
  for (const w of allWraps) {
    if (w === wrap) found = true;
    if (found) w.remove();
  }

  // Add the edited user message and a placeholder AI response
  appendMessage('user', content, false, null, null);
  const aiWrap = appendMessage('assistant', '', true, null, null);
  scrollToBottom();

  await streamResponse(`/api/conversations/${currentConvId}/messages/${seq}`, 'PUT', { content, model: currentModel }, aiWrap);
}

function cancelEditMessage(seq, btn) {
  // Reload the conversation to restore original state
  if (currentConvId) loadConversation(currentConvId);
}

// ── Retry / Regenerate ─────────────────────────────────────────────────────
function toggleRetryMenu(btn) {
  // Close any other open menus
  document.querySelectorAll('.retry-menu.show').forEach(m => {
    if (m !== btn.closest('.msg-actions').querySelector('.retry-menu')) {
      m.classList.remove('show');
      m.closest('.msg-actions')?.classList.remove('pinned');
    }
  });
  const actions = btn.closest('.msg-actions');
  const menu = actions.querySelector('.retry-menu');
  if (menu) {
    menu.classList.toggle('show');
    if (menu.classList.contains('show')) {
      actions.classList.add('pinned');
    } else {
      actions.classList.remove('pinned');
    }
  }
}

async function doRetry(seq, instruction, model) {
  if (!currentConvId || isStreaming) return;
  // Close menu
  document.querySelectorAll('.retry-menu.show').forEach(m => {
    m.classList.remove('show');
    m.closest('.msg-actions')?.classList.remove('pinned');
  });

  // Find and remove the AI message wrap from DOM
  const allWraps = document.querySelectorAll('.msg-wrap');
  let targetWrap = null;
  for (const w of allWraps) {
    if (w.dataset.seq == seq && w.classList.contains('msg-assistant')) { targetWrap = w; break; }
  }

  let aiWrap;
  if (targetWrap) {
    // Replace with streaming placeholder
    targetWrap.querySelector('.msg-content').innerHTML = '<span class="thinking">正在思考...</span>';
    const actions = targetWrap.querySelector('.msg-actions');
    if (actions) actions.style.display = 'none';
    aiWrap = targetWrap;
  } else {
    aiWrap = appendMessage('assistant', '', true, null, null);
  }
  scrollToBottom();

  const body = {};
  if (model) body.model = model;
  if (instruction) body.instruction = instruction;

  await streamResponse(`/api/conversations/${currentConvId}/messages/${seq}/retry`, 'POST', body, aiWrap);

  // Update model selector if model was changed
  if (model) {
    const modelItems = document.querySelectorAll('.model-item');
    for (const item of modelItems) {
      if (item.dataset.id === model) {
        selectModel(model, item.textContent.trim());
        break;
      }
    }
  }
}

function retrySimple(seq) { doRetry(seq, null, null); }
function retryDetailed(seq) { doRetry(seq, '请提供更详细的回答，包含更多细节和解释', null); }
function retryConcise(seq) { doRetry(seq, '请用更简洁的方式回答', null); }

function retryWithInstruction(seq) {
  const instruction = prompt('输入追加指令（如"更详细"、"用中文回答"等）');
  if (instruction && instruction.trim()) doRetry(seq, instruction.trim(), null);
}

function retryWithModel(seq) {
  // Show a small model picker
  const menu = document.querySelector(`.retry-menu[data-seq="${seq}"]`);
  if (menu) menu.classList.remove('show');

  const overlay = document.createElement('div');
  overlay.className = 'retry-model-overlay';
  overlay.onclick = () => overlay.remove();

  const picker = document.createElement('div');
  picker.className = 'retry-model-picker';
  picker.innerHTML = '<div class="retry-model-title">选择模型重新生成</div>';
  picker.onclick = e => e.stopPropagation();

  const models = [
    {id:'gpt-5-2',name:'GPT-5.2'},{id:'gpt-5-2-thinking',name:'GPT-5.2 Thinking'},
    {id:'claude-opus-4',name:'Claude Opus 4'},{id:'claude-4.6-sonnet',name:'Claude 4.6 Sonnet'},
    {id:'gemini-pro',name:'Gemini 3.1 Pro'},{id:'grok-4',name:'Grok 4'},
    {id:'deepseek-r1',name:'Deepseek R1'},{id:'deepseek-v3',name:'Deepseek V3'},
  ];
  for (const m of models) {
    const item = document.createElement('div');
    item.className = 'retry-model-item';
    item.textContent = m.name;
    item.onclick = () => { overlay.remove(); doRetry(seq, null, m.id); };
    picker.appendChild(item);
  }
  overlay.appendChild(picker);
  document.body.appendChild(overlay);
}

// ── Message rendering ──────────────────────────────────────────────────────
function renderAttachmentPreviewHtml(attachments) {
  if (!attachments || attachments.length === 0) return '';
  let html = '<div class="msg-attachments">';
  for (const a of attachments) {
    const name = escapeHtml(a.name || 'file');
    const size = formatFileSize(Number(a.size_bytes) || 0);
    const mime = String(a.mime_type || '');
    if (mime.startsWith('image/') && a.preview_url) {
      html += `<div class="msg-attachment-item image"><img src="${a.preview_url}" class="msg-attachment-thumb" alt="${name}"><div class="msg-attachment-meta">🖼️ ${name} (${size})</div></div>`;
    } else {
      html += `<div class="msg-attachment-item">📄 ${name} (${size})</div>`;
    }
  }
  html += '</div>';
  return html;
}

function appendMessage(role, content, streaming, seq, model, attachments = null) {
  const el = document.getElementById('messages');
  const wrap = document.createElement('div');
  wrap.className = `msg-wrap msg-${role}`;
  if (seq) wrap.dataset.seq = seq;

  if (role === 'user') {
    const attachHtml = renderAttachmentPreviewHtml(attachments);
    wrap.innerHTML = `${attachHtml}<div class="msg-content user-msg">${escapeHtml(content)}</div>
      <div class="msg-edit-actions"${seq ? '' : ' style="display:none"'}>
        <button class="edit-msg-btn" onclick="startEditMessage(${seq}, this.closest('.msg-wrap'))" title="编辑">✏️</button>
      </div>`;
  } else {
    const body = streaming ? '<span class="thinking">正在思考...</span>' : renderMd(content);
    const seqAttr = seq || 0;
    wrap.innerHTML = `<div class="msg-content assistant-msg">${body}</div>
      <div class="msg-actions"${streaming ? ' style="display:none"' : ''}>
        <button onclick="copyMsg(this)" title="复制全文">📋</button>
        <button onclick="this.style.opacity=this.style.opacity==='1'?'0.4':'1'" title="点赞">👍</button>
        <button onclick="this.style.opacity=this.style.opacity==='1'?'0.4':'1'" title="点踩">👎</button>
        <button class="retry-toggle-btn" onclick="toggleRetryMenu(this)" title="重新生成">🔄</button>
        <div class="retry-menu" data-seq="${seqAttr}">
          <div class="retry-menu-item" onclick="retrySimple(${seqAttr})">🔄 重试</div>
          <div class="retry-menu-item" onclick="retryWithInstruction(${seqAttr})">💬 要求更改回复</div>
          <div class="retry-menu-item" onclick="retryDetailed(${seqAttr})">📝 添加详细信息</div>
          <div class="retry-menu-item" onclick="retryConcise(${seqAttr})">✂️ 更加简洁</div>
          <div class="retry-menu-item" onclick="retryWithModel(${seqAttr})">🔀 切换模型</div>
          <div class="retry-menu-item disabled">🔍 搜索网页（即将推出）</div>
        </div>
      </div>`;
  }
  el.appendChild(wrap);
  return wrap;
}

function setMsgContent(wrap, text, streaming) {
  const c = wrap.querySelector('.msg-content');
  const a = wrap.querySelector('.msg-actions');
  if (streaming) {
    c.innerHTML = renderMd(text) + '<span class="cursor">▋</span>';
  } else {
    c.innerHTML = renderMd(text);
    if (a) a.style.removeProperty('display');
  }
  scrollToBottom();
}

function renderMd(text) {
  if (!text) return '';
  try { return marked.parse(text); } catch(e) { return escapeHtml(text); }
}

// ── Helpers ────────────────────────────────────────────────────────────────
function copyMsg(btn) {
  const text = btn.closest('.msg-wrap').querySelector('.msg-content').innerText;
  navigator.clipboard.writeText(text).then(() => {
    btn.textContent = '✅'; setTimeout(() => btn.textContent = '📋', 2000);
  });
}

function copyCode(btn) {
  const code = btn.closest('.code-block-wrap').querySelector('code').innerText;
  navigator.clipboard.writeText(code).then(() => {
    btn.textContent = '已复制'; setTimeout(() => btn.textContent = '复制', 2000);
  });
}

function logout() {
  localStorage.removeItem('token'); localStorage.removeItem('user');
  window.location.href = '/login';
}

function escapeHtml(s) {
  return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}

function scrollToBottom() {
  const el = document.getElementById('messages');
  requestAnimationFrame(() => { el.scrollTop = el.scrollHeight; });
}

function updateSendBtn() {
  const btn = document.getElementById('send-btn');
  btn.classList.toggle('stop', isStreaming);
  btn.innerHTML = isStreaming
    ? '<svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor"><rect x="4" y="4" width="16" height="16" rx="2"/></svg>'
    : '<svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor"><path d="M2.01 21L23 12 2.01 3 2 10l15 2-15 2z"/></svg>';
}

function openSidebar() {
  document.getElementById('sidebar').classList.add('open');
  document.getElementById('overlay').classList.add('show');
}

function toggleSidebar() {
  const sidebar = document.getElementById('sidebar');
  if (sidebar.classList.contains('open')) closeSidebar();
  else openSidebar();
}

function closeSidebar() {
  document.getElementById('sidebar').classList.remove('open');
  document.getElementById('overlay').classList.remove('show');
}

// ── Event listeners ────────────────────────────────────────────────────────
document.addEventListener('click', e => {
  if (!e.target.closest('.model-selector-btn') && !e.target.closest('.model-dropdown'))
    document.getElementById('model-dropdown').style.display = 'none';
  // Close retry menus when clicking outside
  if (!e.target.closest('.retry-toggle-btn') && !e.target.closest('.retry-menu'))
    document.querySelectorAll('.retry-menu.show').forEach(m => {
      m.classList.remove('show');
      m.closest('.msg-actions')?.classList.remove('pinned');
    });
});

const msgInput = document.getElementById('msg-input');
msgInput.addEventListener('input', function() {
  this.style.height = 'auto';
  this.style.height = Math.min(this.scrollHeight, 200) + 'px';
});
msgInput.addEventListener('keydown', e => {
  if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendMessage(); }
});
document.addEventListener('keydown', e => {
  if (e.key === 'Escape') document.querySelectorAll('.retry-menu.show').forEach(m => {
    m.classList.remove('show');
    m.closest('.msg-actions')?.classList.remove('pinned');
  });
  if ((e.ctrlKey || e.metaKey) && e.key === 'n') { e.preventDefault(); newConversation(); }
});
document.getElementById('search-input').addEventListener('input', renderConversations);

function initMobileSidebarGesture() {
  let startX = 0;
  let startY = 0;
  const threshold = 48;

  document.addEventListener('touchstart', e => {
    if (!e.touches || e.touches.length !== 1) return;
    startX = e.touches[0].clientX;
    startY = e.touches[0].clientY;
  }, { passive: true });

  document.addEventListener('touchend', e => {
    if (!e.changedTouches || e.changedTouches.length !== 1) return;
    if (window.innerWidth > 768) return;

    const endX = e.changedTouches[0].clientX;
    const endY = e.changedTouches[0].clientY;
    const dx = endX - startX;
    const dy = endY - startY;
    if (Math.abs(dy) > 60 || Math.abs(dx) < threshold) return;

    const sidebarOpen = document.getElementById('sidebar').classList.contains('open');
    if (!sidebarOpen && startX <= 24 && dx > 0) openSidebar();
    if (sidebarOpen && dx < 0) closeSidebar();
  }, { passive: true });
}

// ── Start ──────────────────────────────────────────────────────────────────
init();
bindWelcomePrompts();
initMobileSidebarGesture();
