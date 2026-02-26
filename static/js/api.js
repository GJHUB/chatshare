// API base (same origin)
const API_BASE = '';

async function apiFetch(path, options = {}) {
  const token = localStorage.getItem('token');
  const headers = {
    'Content-Type': 'application/json',
    ...(token ? { Authorization: `Bearer ${token}` } : {}),
    ...(options.headers || {}),
  };
  const resp = await fetch(API_BASE + path, { ...options, headers });
  if (resp.status === 401) {
    localStorage.removeItem('token');
    localStorage.removeItem('user');
    window.location.href = '/login';
    return null;
  }
  return resp;
}

async function apiJSON(path, options = {}) {
  const resp = await apiFetch(path, options);
  if (!resp) return null;
  if (!resp.ok) {
    const err = await resp.json().catch(() => ({ detail: resp.statusText }));
    throw new Error(err.detail || 'Request failed');
  }
  return resp.json();
}

// Auth
const authAPI = {
  register: (data) => apiJSON('/api/auth/register', { method: 'POST', body: JSON.stringify(data) }),
  login: (data) => apiJSON('/api/auth/login', { method: 'POST', body: JSON.stringify(data) }),
  me: () => apiJSON('/api/auth/me'),
};

// Conversations
const convAPI = {
  list: () => apiJSON('/api/conversations'),
  create: (data = {}) => apiJSON('/api/conversations', { method: 'POST', body: JSON.stringify(data) }),
  update: (id, data) => apiJSON(`/api/conversations/${id}`, { method: 'PUT', body: JSON.stringify(data) }),
  delete: (id) => apiJSON(`/api/conversations/${id}`, { method: 'DELETE' }),
};

// Messages
const msgAPI = {
  list: (convId) => apiJSON(`/api/conversations/${convId}/messages`),
  send: (convId, data) => apiFetch(`/api/conversations/${convId}/messages`, { method: 'POST', body: JSON.stringify(data) }),
};

// Models
const modelAPI = {
  list: () => apiJSON('/api/models'),
};
