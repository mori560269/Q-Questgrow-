// 共通ユーティリティ
export const $ = (sel, root = document) => root.querySelector(sel);
export const h = (tag, attrs = {}, ...children) => {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k === 'class') el.className = v;
    else if (k.startsWith('on')) el.addEventListener(k.slice(2), v);
    else if (v !== false && v != null) el.setAttribute(k, v === true ? '' : v);
  }
  for (const c of children.flat()) if (c != null && c !== false) el.append(c instanceof Node ? c : document.createTextNode(String(c)));
  return el;
};

export class AuthError extends Error {}
export class NetworkError extends Error {}

export async function api(path, { method = 'GET', body, timeout = 5000 } = {}) {
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), timeout);
  let res;
  try {
    res = await fetch(path, {
      method,
      headers: body ? { 'Content-Type': 'application/json' } : {},
      body: body ? JSON.stringify(body) : undefined,
      signal: ctrl.signal,
      credentials: 'same-origin',
    });
  } catch (e) {
    throw new NetworkError(e.message);
  } finally {
    clearTimeout(timer);
  }
  if (res.status === 401) throw new AuthError('ログインしてください');
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw Object.assign(new Error(data.error || (data.errors || []).join('\n') || `エラー (${res.status})`), { data });
  return data;
}

export function fmtTime(iso) {
  if (!iso) return '';
  const d = new Date(iso);
  return d.toLocaleTimeString('ja-JP', { hour: '2-digit', minute: '2-digit', second: '2-digit' });
}
export function fmtDateTime(iso) {
  if (!iso) return '';
  return new Date(iso).toLocaleString('ja-JP', { month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit' });
}
export const fmtId = (id) => `${id.slice(0, 5)}-${id.slice(5)}`;

// ログインフォームを出し、成功したら resolve
export function showLogin(container, { title, onSuccess }) {
  container.replaceChildren();
  const err = h('div', { class: 'err' });
  const input = h('input', { type: 'password', placeholder: 'パスワード', autocomplete: 'current-password', required: true });
  const btn = h('button', { class: 'primary', type: 'submit' }, 'ログイン');
  const form = h('form', {
    onsubmit: async (e) => {
      e.preventDefault();
      btn.disabled = true; err.textContent = '';
      try {
        const r = await api('/api/login', { method: 'POST', body: { password: input.value } });
        onSuccess(r.role);
      } catch (ex) {
        err.textContent = ex instanceof NetworkError ? 'サーバーにつながりません' : ex.message;
      } finally { btn.disabled = false; }
    },
  }, input, btn, err);
  container.append(h('div', { class: 'login' }, h('h1', {}, title), form));
  input.focus();
}
