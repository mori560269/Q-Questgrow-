import { $, h, api, AuthError, NetworkError, fmtTime, fmtId, showLogin } from './common.js';

// ===== 端末内に保存する状態 =====
const store = {
  get(k, d) { try { const v = localStorage.getItem(k); return v ? JSON.parse(v) : d; } catch { return d; } },
  set(k, v) { try { localStorage.setItem(k, JSON.stringify(v)); } catch {} },
};
const deviceId = store.get('device', null) || (() => { const id = 'dev-' + Math.random().toString(36).slice(2, 8); store.set('device', id); return id; })();
let snapshot = store.get('snapshot', { at: null, tickets: {} }); // id → {name, ticket_type, status, checked_in_at, gate}
let queue = store.get('queue', []);     // オフライン中のスキャン
let conflicts = store.get('conflicts', []);
let online = navigator.onLine;
let me = null;
let scanner = null;
let busy = false;
let lastText = '', lastAt = 0;

const app = $('#app');
if ('serviceWorker' in navigator) navigator.serviceWorker.register('/sw.js').catch(() => {});

boot();

async function boot() {
  try {
    me = await api('/api/me');
  } catch {
    // オフラインで開いた場合は前回の情報で起動する
    me = store.get('me', null);
    if (!me) return app.replaceChildren(h('div', { class: 'login' }, h('h1', {}, 'サーバーにつながりません'), h('p', { class: 'muted' }, '電波のある場所で一度開いてください。')));
    online = false;
  }
  if (!me.role) return showLogin(app, { title: '入場チェック ログイン', onSuccess: () => boot() });
  store.set('me', me);
  renderMain();
}

function renderMain() {
  app.replaceChildren($('#tpl-main').content.cloneNode(true));
  $('#event-name').textContent = me.eventName;
  const gateSel = $('#gate');
  for (const g of me.gates) gateSel.append(h('option', { value: g }, g));
  gateSel.value = store.get('gate', me.gates[0]);
  gateSel.onchange = () => store.set('gate', gateSel.value);
  $('#logout').onclick = async () => { if (!confirm('ログアウトしますか?')) return; await api('/api/logout', { method: 'POST' }).catch(() => {}); location.reload(); };
  $('#btn-manual').onclick = openManual;
  $('#btn-camera').onclick = () => startCamera(true);
  window.addEventListener('online', () => { setOnline(true); sync(); });
  window.addEventListener('offline', () => setOnline(false));
  setOnline(online);
  renderStatus();
  refreshSnapshot();
  setInterval(refreshSnapshot, 30000);
  setInterval(sync, 5000);
  startCamera();
}

// ===== カメラ =====
async function startCamera(restart = false) {
  const msg = $('#cam-msg');
  try {
    if (scanner && restart) { await scanner.stop().catch(() => {}); scanner.clear(); scanner = null; }
    if (scanner) return;
    scanner = new Html5Qrcode('reader', { formatsToSupport: [Html5QrcodeSupportedFormats.QR_CODE], verbose: false });
    await scanner.start({ facingMode: 'environment' }, { fps: 12, qrbox: (w, hgt) => { const s = Math.floor(Math.min(w, hgt) * 0.7); return { width: s, height: s }; } }, onDecoded, () => {});
    msg.textContent = 'QRコードを枠の中に映してください';
  } catch (e) {
    scanner = null;
    msg.textContent = location.protocol !== 'https:' && location.hostname !== 'localhost'
      ? 'カメラを使うには https:// のURLで開く必要があります'
      : 'カメラを起動できません。ブラウザのカメラ許可を確認してください。';
  }
}

function onDecoded(text) {
  const now = Date.now();
  if (busy) return;
  if (text === lastText && now - lastAt < 4000) return; // 同じQRの連続読み取りを無視
  lastText = text; lastAt = now;
  handle(text);
}

// ===== 判定 =====
async function handle(input, manual = false) {
  busy = true;
  const gate = $('#gate').value;
  let res;
  if (online || manual) {
    try {
      res = await api('/api/checkin', { method: 'POST', body: { input, gate, device: deviceId }, timeout: 4000 });
      setOnline(true);
      if (res.ticket) updateLocal(res.ticket);
    } catch (e) {
      if (e instanceof AuthError) { busy = false; return showLogin(app, { title: 'ログインが切れました', onSuccess: () => boot() }); }
      if (!(e instanceof NetworkError)) { busy = false; return alert(e.message); }
      setOnline(false);
    }
  }
  if (!res) res = offlineCheck(input, gate);
  feedback(res);
  showResult(res);
  renderStatus();
}

// 電波がないときは、端末に保存したチケット一覧で判定してあとで送る
function offlineCheck(input, gate) {
  const raw = String(input).trim();
  const parts = raw.split('.');
  const id = parts.length === 3 && parts[0] === 'T1' ? parts[1] : raw.toUpperCase().replace(/[\s-]/g, '');
  const t = snapshot.tickets[id];
  if (!t) return { result: 'invalid', reason: '一覧にないチケットです', offline: true };
  if (t.status === 'cancelled') return { result: 'cancelled', reason: 'キャンセル済みのチケットです', ticket: { id, ...t }, offline: true };
  if (t.checked_in_at) return { result: 'duplicate', reason: '入場済みのチケットです', ticket: { id, ...t }, offline: true };
  const at = new Date().toISOString();
  t.checked_in_at = at; t.gate = gate;
  queue.push({ local_id: `${deviceId}-${Date.now()}`, input: raw, gate, device: deviceId, scanned_at: at });
  store.set('queue', queue); store.set('snapshot', snapshot);
  return { result: 'ok', ticket: { id, ...t }, offline: true };
}

function updateLocal(t) {
  snapshot.tickets[t.id] = { name: t.name, ticket_type: t.ticket_type, status: t.status, checked_in_at: t.checked_in_at, gate: t.gate };
  store.set('snapshot', snapshot);
}

// ===== 同期 =====
async function refreshSnapshot() {
  try {
    const r = await api('/api/snapshot', { timeout: 10000 });
    const map = {};
    for (const t of r.tickets) map[t.id] = { name: t.name, ticket_type: t.ticket_type, status: t.status, checked_in_at: t.checked_in_at, gate: t.gate };
    // 未送信のオフライン入場は端末側の状態を優先
    for (const q of queue) { const id = q.input.split('.')[1] || q.input; if (map[id] && !map[id].checked_in_at) { map[id].checked_in_at = q.scanned_at; map[id].gate = q.gate; } }
    snapshot = { at: r.at, tickets: map };
    store.set('snapshot', snapshot);
    setOnline(true);
    renderStatus();
  } catch (e) {
    if (e instanceof AuthError) return showLogin(app, { title: 'ログインが切れました', onSuccess: () => boot() });
    if (e instanceof NetworkError) setOnline(false);
  }
}

let syncing = false;
async function sync() {
  if (syncing || !queue.length) return;
  syncing = true;
  try {
    const items = queue.slice();
    const r = await api('/api/sync', { method: 'POST', body: { items }, timeout: 10000 });
    const done = new Set(items.map((i) => i.local_id));
    queue = queue.filter((q) => !done.has(q.local_id));
    for (const x of r.results) {
      if (x.ticket) updateLocal(x.ticket);
      // オフラインで通したが、サーバーでは別の場所で入場済みだった
      if (x.result !== 'ok') conflicts.push({ at: new Date().toISOString(), name: x.ticket?.name || '(不明)', reason: x.reason, other: x.ticket ? `${x.ticket.gate || ''} ${fmtTime(x.ticket.checked_in_at)}` : '' });
    }
    store.set('queue', queue); store.set('conflicts', conflicts);
    setOnline(true);
  } catch (e) {
    if (e instanceof NetworkError) setOnline(false);
  } finally {
    syncing = false;
    renderStatus();
  }
}

// ===== 表示 =====
function setOnline(v) {
  online = v;
  const el = $('#net');
  if (!el) return;
  el.className = `net ${v ? 'on' : 'off'}`;
  el.textContent = v ? 'オンライン' : 'オフライン';
}

function renderStatus() {
  if (!$('#count')) return;
  const all = Object.values(snapshot.tickets).filter((t) => t.status === 'valid');
  const checked = all.filter((t) => t.checked_in_at).length;
  $('#count').textContent = `入場 ${checked} / ${all.length}`;
  $('#last-sync').textContent = snapshot.at ? `一覧更新 ${fmtTime(snapshot.at)}` : '';
  $('#pending').textContent = queue.length ? `未送信 ${queue.length}件` : '';
  const banners = $('#banners');
  banners.replaceChildren();
  if (conflicts.length) {
    banners.append(h('div', { class: 'banner' },
      h('b', {}, `オフライン中に通した ${conflicts.length} 件が、別の場所で入場済みでした`),
      h('ul', { style: 'margin:6px 0;padding-left:18px' }, conflicts.slice(-5).map((c) => h('li', {}, `${c.name} — ${c.other}`))),
      h('button', { onclick: () => { conflicts = []; store.set('conflicts', conflicts); renderStatus(); } }, '確認した')));
  }
}

const LABELS = {
  ok: { icon: '✓', head: '入場OK' },
  duplicate: { icon: '✕', head: '入場済み' },
  invalid: { icon: '✕', head: '無効なチケット' },
  cancelled: { icon: '!', head: 'キャンセル済み' },
};

function showResult(res) {
  const l = LABELS[res.result] || LABELS.invalid;
  const t = res.ticket;
  let sub = res.reason || '';
  if (res.result === 'duplicate' && t?.checked_in_at) sub = `${fmtTime(t.checked_in_at)} に ${t.gate || ''} で入場済み`;
  if (res.offline) sub += (sub ? ' ' : '') + '(オフライン判定)';
  const el = h('div', { class: `result ${res.result}`, role: 'alert' },
    h('div', { class: 'icon' }, l.icon),
    h('div', { class: 'head' }, l.head),
    sub && h('div', { class: 'sub' }, sub),
    t && h('div', { class: 'name' }, `${t.name} 様`),
    t && h('div', { class: 'type' }, t.ticket_type),
    h('div', { class: 'tap' }, 'タップして次へ'));
  const close = () => { el.remove(); busy = false; clearTimeout(timer); };
  el.addEventListener('click', close);
  document.body.append(el);
  // OKは自動で閉じる。NGはスタッフが確認してタップするまで残す
  const timer = res.result === 'ok' ? setTimeout(close, 1800) : null;
}

let audio;
function feedback(res) {
  try {
    audio ||= new AudioContext();
    const ok = res.result === 'ok';
    const tones = ok ? [[1320, 0, 0.12]] : [[220, 0, 0.18], [220, 0.25, 0.18]];
    for (const [f, start, dur] of tones) {
      const o = audio.createOscillator(); const g = audio.createGain();
      o.type = ok ? 'sine' : 'square'; o.frequency.value = f;
      g.gain.value = 0.2;
      o.connect(g).connect(audio.destination);
      o.start(audio.currentTime + start); o.stop(audio.currentTime + start + dur);
    }
    navigator.vibrate?.(ok ? 80 : [200, 100, 200]);
  } catch {}
}

// ===== 手動受付(スマホを忘れた・QRが読めない人) =====
function openManual() {
  busy = true;
  const list = h('div', { class: 'list' }, h('p', { class: 'muted' }, '氏名・メールアドレス・注文番号・チケット番号で検索できます。'));
  const input = h('input', { type: 'search', placeholder: '例: 山田 / ABCDE-FGHJK', enterkeyhint: 'search' });
  const close = () => { sheet.remove(); busy = false; };
  let timer;
  const run = async () => {
    const q = input.value.trim();
    if (q.length < 2) return;
    let tickets;
    try {
      tickets = (await api(`/api/search?q=${encodeURIComponent(q)}`)).tickets;
    } catch (e) {
      // オフライン時は端末内の一覧から名前で探す
      const ql = q.toLowerCase(); const qid = q.toUpperCase().replace(/[\s-]/g, '');
      tickets = Object.entries(snapshot.tickets).filter(([id, t]) => id === qid || t.name.toLowerCase().includes(ql)).slice(0, 30).map(([id, t]) => ({ id, ...t, email: '' }));
    }
    list.replaceChildren(...(tickets.length ? tickets.map(item) : [h('p', { class: 'muted' }, '見つかりませんでした')]));
  };
  const item = (t) => {
    const state = t.status === 'cancelled' ? h('span', { class: 'chip warn' }, 'キャンセル')
      : t.checked_in_at ? h('span', { class: 'chip ng' }, `入場済 ${fmtTime(t.checked_in_at)}`)
      : h('span', { class: 'chip ok' }, '未入場');
    return h('div', { class: 'item' },
      h('div', { class: 'grow' },
        h('div', {}, h('b', {}, t.name), ' ', h('span', { class: 'chip' }, t.ticket_type), ' ', state),
        h('div', { class: 'meta mono' }, fmtId(t.id), t.order_no ? ` / ${t.order_no}` : '', t.email ? ` / ${t.email}` : '')),
      h('button', {
        class: 'primary', disabled: t.status !== 'valid' || !!t.checked_in_at,
        onclick: async () => { if (!confirm(`${t.name} 様を入場させますか?`)) return; sheet.remove(); await handle(t.id, true); },
      }, '入場'));
  };
  input.addEventListener('input', () => { clearTimeout(timer); timer = setTimeout(run, 300); });
  const sheet = h('div', { class: 'sheet' },
    h('div', { class: 'bar row' }, h('div', { class: 'grow' }, input), h('button', { onclick: close }, '閉じる')),
    list);
  document.body.append(sheet);
  input.focus();
}
