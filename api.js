/**
 * BotNesia — API Client
 * Hubungkan ke: src/api.js
 *
 * Cara pakai:
 *   import API from './api.js';
 *   const { token } = await API.auth.login(email, password);
 *
 * Konfigurasi BASE_URL lewat:
 *   localStorage.setItem('bn_api_url', 'https://api.botnesia.id/v1')
 *   atau biarkan default ke localhost:8000
 */

const DEFAULT_API_BASE =
  (location.protocol === 'http:' || location.protocol === 'https:')
    ? location.origin
    : 'http://localhost:8000';

const API_BASE = localStorage.getItem('bn_api_url') || DEFAULT_API_BASE;

// ─── TOKEN STORE ──────────────────────────────────────────────
const token = {
  get()        { return localStorage.getItem('bn_token'); },
  set(t)       { localStorage.setItem('bn_token', t); },
  clear()      { localStorage.removeItem('bn_token'); },
};

// ─── REQUEST HELPER ───────────────────────────────────────────
async function req(method, path, body, isFormData = false) {
  const headers = {};

  if (!isFormData) headers['Content-Type'] = 'application/json';
  if (token.get()) headers['Authorization'] = `Bearer ${token.get()}`;

  const opts = { method, headers };
  if (body) opts.body = isFormData ? body : JSON.stringify(body);

  const res = await fetch(`${API_BASE}${path}`, opts);

  // 401 → paksa logout
  if (res.status === 401) {
    token.clear();
    window.dispatchEvent(new CustomEvent('bn:unauthorized'));
    throw new APIError(401, 'Sesi berakhir. Silakan login ulang.');
  }

  const data = await res.json().catch(() => ({}));

  if (!res.ok) {
    throw new APIError(res.status, data.detail || `Error ${res.status}`);
  }

  return data;
}

class APIError extends Error {
  constructor(status, message) {
    super(message);
    this.status  = status;
    this.isAPI   = true;
  }
}

// ─── AUTH ─────────────────────────────────────────────────────
const auth = {
  async login(email, password) {
    const data = await req('POST', '/auth/login', { email, password });
    token.set(data.token);
    return data;
  },

  async register(orgName, email, password, fullName) {
    const data = await req('POST', '/auth/register', {
      org_name: orgName, email, password, full_name: fullName,
    });
    token.set(data.token);
    return data;
  },

  logout() {
    token.clear();
    window.dispatchEvent(new CustomEvent('bn:logout'));
  },

  isLoggedIn() {
    return !!token.get();
  },
};

// ─── BOTS ─────────────────────────────────────────────────────
const bots = {
  list() {
    return req('GET', '/bots');
  },

  create({ name, primaryColor, greeting, systemPrompt, language }) {
    return req('POST', '/bots', {
      name,
      primary_color: primaryColor || '#0066FF',
      greeting:      greeting     || 'Halo! Ada yang bisa saya bantu?',
      system_prompt: systemPrompt || null,
      language:      language     || 'id',
    });
  },

  update(botId, changes) {
    // changes: { name, primaryColor, greeting, systemPrompt, language }
    const body = {};
    if (changes.name)         body.name          = changes.name;
    if (changes.primaryColor) body.primary_color = changes.primaryColor;
    if (changes.greeting)     body.greeting      = changes.greeting;
    if (changes.systemPrompt !== undefined) body.system_prompt = changes.systemPrompt;
    if (changes.language)     body.language      = changes.language;
    return req('PATCH', `/bots/${botId}`, body);
  },

  getConfig(botId) {
    // Public — tidak perlu token
    return fetch(`${API_BASE}/bots/${botId}/config`)
      .then(r => r.json());
  },

  getAnalytics(botId, days = 30) {
    return req('GET', `/bots/${botId}/analytics?days=${days}`);
  },
};

// ─── DOCUMENTS ────────────────────────────────────────────────
const documents = {
  list(botId) {
    return req('GET', `/bots/${botId}/documents`);
  },

  async upload(botId, file, onProgress) {
    const form = new FormData();
    form.append('file', file);

    // XMLHttpRequest untuk progress tracking
    return new Promise((resolve, reject) => {
      const xhr = new XMLHttpRequest();
      xhr.open('POST', `${API_BASE}/bots/${botId}/documents`);
      xhr.setRequestHeader('Authorization', `Bearer ${token.get()}`);

      if (onProgress) {
        xhr.upload.onprogress = e => {
          if (e.lengthComputable) onProgress(Math.round(e.loaded / e.total * 100));
        };
      }

      xhr.onload = () => {
        try {
          const data = JSON.parse(xhr.responseText);
          if (xhr.status >= 200 && xhr.status < 300) resolve(data);
          else reject(new APIError(xhr.status, data.detail || `Upload error ${xhr.status}`));
        } catch { reject(new APIError(0, 'Parse error')); }
      };

      xhr.onerror = () => reject(new APIError(0, 'Network error'));
      xhr.send(form);
    });
  },

  // Poll status sampai 'ready' atau 'failed'
  async waitUntilReady(botId, docId, intervalMs = 2000, timeoutMs = 60000) {
    const start = Date.now();
    while (Date.now() - start < timeoutMs) {
      const docs = await documents.list(botId);
      const doc  = docs.find(d => d.id === docId);
      if (!doc) throw new APIError(404, 'Dokumen tidak ditemukan');
      if (doc.status === 'ready')  return doc;
      if (doc.status === 'failed') throw new APIError(500, doc.error_msg || 'Processing gagal');
      await new Promise(r => setTimeout(r, intervalMs));
    }
    throw new APIError(408, 'Timeout menunggu dokumen diproses');
  },
};

// ─── CONVERSATIONS ────────────────────────────────────────────
const conversations = {
  list(botId, { limit = 20, offset = 0 } = {}) {
    return req('GET', `/bots/${botId}/conversations?limit=${limit}&offset=${offset}`);
  },

  getMessages(convId) {
    return req('GET', `/conversations/${convId}/messages`);
  },
};

// ─── CHAT ─────────────────────────────────────────────────────
const chat = {
  /**
   * Kirim pesan ke bot.
   * @param {string} botId
   * @param {string} message
   * @param {string|null} sessionId  - UUID conv aktif, null = mulai baru
   * @param {object|null} userMeta   - dari ChatbotWidget.identify()
   * @returns {{ answer, session_id, latency_ms }}
   */
  send(botId, message, sessionId = null, userMeta = null) {
    return req('POST', `/chat/${botId}`, {
      message,
      session_id: sessionId,
      user_meta:  userMeta,
    });
  },
};

// ─── WEBHOOKS ─────────────────────────────────────────────────
const webhooks = {
  create(url, events) {
    return req('POST', '/webhooks', { url, events });
  },
};

// ─── API KEYS ─────────────────────────────────────────────────
const apiKeys = {
  create(name) {
    return req('POST', '/api-keys', { name });
  },
};

// ─── HEALTH ───────────────────────────────────────────────────
async function health() {
  const res = await fetch(`${API_BASE}/health`);
  return res.json();
}

// ─── EXPORT ───────────────────────────────────────────────────
const API = {
  auth, bots, documents, conversations, chat,
  webhooks, apiKeys, health,
  token, APIError,
  setBaseUrl(url) { localStorage.setItem('bn_api_url', url); },
};

export default API;
