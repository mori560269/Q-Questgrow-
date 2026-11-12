import { $, h, api, AuthError, fmtTime, fmtDateTime, fmtId, showLogin } from './common.js';

const app = $('#app');
let me, tab = 'live', stats = null, tickets = [], filter = '';
let timer;

boot();

async function boot() {
  me = await api('/api/me');
  if (me.role !== 'admin') {
    return showLogin(app, { title: '管理画面 ログイン(管理者パスワード)', onSuccess: (role) => role === 'admin' ? boot() : alert('管理者パスワードでログインしてください') });
  }
  document.title = `入場管理 — ${me.eventName}`;
  render();
  clearInterval(timer);
  timer = setInterval(() => { if (tab === 'live') load(); }, 5000);
}

async function load() {
  try {
    if (tab === 'live') stats = await api('/api/stats');
    if (tab === 'tickets') tickets = (await api('/api/tickets')).tickets;
    if (tab === 'tools') stats = await api('/api/stats');
    renderBody();
  } catch (e) {
    if (e instanceof AuthError) return boot();
  }
}

function render() {
  const tabs = [['live', '当日の状況'], ['tickets', 'チケット一覧'], ['tools', '準備(取込・メール)']];
  app.replaceChildren(h('div', { class: 'admin' },
    h('header', {},
      h('h1', {}, me.eventName),
      h('div', { class: 'row' },
        h('a', { href: '/scan', target: '_blank' }, h('button', {}, 'スキャン画面')),
        h('button', { onclick: async () => { await api('/api/logout', { method: 'POST' }); location.reload(); } }, 'ログアウト'))),
    h('div', { class: 'tabs' }, tabs.map(([k, label]) => h('button', { class: tab === k ? 'active' : '', onclick: () => { tab = k; render(); } }, label))),
    h('div', { id: 'body' }, h('p', { class: 'muted' }, '読み込み中…'))));
  load();
}

function renderBody() {
  const body = $('#body');
  if (!body) return;
  if (tab === 'live') body.replaceChildren(...liveView());
  if (tab === 'tickets') body.replaceChildren(...ticketsView());
  if (tab === 'tools') body.replaceChildren(...toolsView());
}

// ===== 当日の状況 =====
const RESULT = { ok: ['入場OK', 'ok'], duplicate: ['入場済み', 'ng'], invalid: ['無効', 'ng'], cancelled: ['キャンセル', 'warn'], undo: ['取消', 'warn'], cancel: ['チケット無効化', 'warn'], restore: ['無効化を解除', 'warn'] };

function liveView() {
  const s = stats;
  const pct = s.total ? Math.round((s.checked / s.total) * 100) : 0;
  const prob = Object.fromEntries(s.problems.map((p) => [p.result, p.n]));
  return [
    h('div', { class: 'kpis' },
      h('div', { class: 'card kpi' }, h('div', { class: 'label' }, '入場者数'), h('div', { class: 'value' }, s.checked, h('small', {}, ` / ${s.total}`)),
        h('div', { class: 'progress' }, h('div', { style: `width:${pct}%` }))),
      h('div', { class: 'card kpi' }, h('div', { class: 'label' }, '未入場'), h('div', { class: 'value' }, s.total - s.checked)),
      ...me.gates.map((g) => h('div', { class: 'card kpi' }, h('div', { class: 'label' }, g), h('div', { class: 'value' }, s.byGate.find((x) => x.gate === g)?.n || 0))),
      h('div', { class: 'card kpi' }, h('div', { class: 'label' }, '入場済みQRの再提示 / 無効QR'), h('div', { class: 'value' }, `${prob.duplicate || 0}`, h('small', {}, ` / ${(prob.invalid || 0) + (prob.cancelled || 0)}`)))),
    h('div', { class: 'grid2' },
      h('div', { class: 'card' }, h('h2', {}, '10分ごとの入場数'), histogram(s.times)),
      h('div', { class: 'card' }, h('h2', {}, '券種別'),
        h('table', {}, h('tr', {}, h('th', {}, '券種'), h('th', {}, '入場'), h('th', {}, '販売')),
          s.byType.map((t) => h('tr', {}, h('td', {}, t.ticket_type), h('td', {}, t.checked), h('td', {}, t.total)))))),
    h('div', { class: 'card' }, h('h2', {}, '最近のスキャン(5秒ごとに更新)'),
      h('div', { class: 'table-wrap' }, h('table', {},
        h('tr', {}, ['時刻', '結果', '氏名', '券種', 'ゲート', '端末'].map((x) => h('th', {}, x))),
        s.recent.map((l) => {
          const [label, cls] = RESULT[l.result] || [l.result, ''];
          return h('tr', {},
            h('td', {}, fmtTime(l.scanned_at), l.offline ? h('span', { class: 'muted' }, ' (オフライン)') : ''),
            h('td', {}, h('span', { class: `chip ${cls}` }, label)),
            h('td', {}, l.name || h('span', { class: 'muted' }, l.input || '')),
            h('td', {}, l.ticket_type || ''), h('td', {}, l.gate || ''), h('td', { class: 'muted' }, l.device || ''));
        })))),
  ];
}

function histogram(times) {
  if (!times.length) return h('p', { class: 'muted' }, 'まだ入場はありません');
  const bucket = 10 * 60 * 1000;
  const ts = times.map((t) => new Date(t).getTime());
  const start = Math.floor(Math.min(...ts) / bucket) * bucket;
  const end = Math.floor(Math.max(...ts) / bucket) * bucket;
  const n = Math.min(48, (end - start) / bucket + 1);
  const counts = Array(n).fill(0);
  for (const t of ts) { const i = Math.floor((t - start) / bucket); if (i < n) counts[i]++; }
  const max = Math.max(...counts);
  const label = (ms) => new Date(ms).toLocaleTimeString('ja-JP', { hour: '2-digit', minute: '2-digit' });
  return h('div', {},
    h('div', { class: 'bars' }, counts.map((c, i) => h('div', { style: `height:${(c / max) * 100}%`, title: `${label(start + i * bucket)}〜 ${c}人` }))),
    h('div', { class: 'bars-x' }, h('span', {}, label(start)), h('span', {}, `最大 ${max}人/10分`), h('span', {}, label(end))));
}

// ===== チケット一覧 =====
function ticketsView() {
  const q = filter.toLowerCase();
  const rows = tickets.filter((t) => !q || [t.name, t.email, t.order_no, t.id, fmtId(t.id)].some((v) => String(v || '').toLowerCase().includes(q)));
  const search = h('input', { type: 'search', placeholder: '氏名・メール・注文番号・チケット番号で絞り込み', value: filter });
  search.addEventListener('input', () => { filter = search.value; const pos = search.selectionStart; renderBody(); const s = $('#body input'); s.focus(); s.setSelectionRange(pos, pos); });
  const act = async (path, body, msg) => { if (msg && !confirm(msg)) return; try { await api(path, { method: 'POST', body }); await load(); } catch (e) { alert(e.message); } };
  return [
    h('div', { class: 'row', style: 'margin-bottom:12px' }, h('div', { class: 'grow' }, search),
      h('a', { href: '/api/export.csv' }, h('button', {}, 'CSV出力'))),
    h('p', { class: 'muted', style: 'font-size:13px' }, `${rows.length} 件`),
    h('div', { class: 'card table-wrap' }, h('table', {},
      h('tr', {}, ['チケット番号', '氏名', 'メール', '券種', '注文番号', 'メール送信', '入場', ''].map((x) => h('th', {}, x))),
      rows.map((t) => h('tr', {},
        h('td', { class: 'mono' }, fmtId(t.id)),
        h('td', {}, t.name, t.status === 'cancelled' ? h('span', { class: 'chip warn', style: 'margin-left:6px' }, '無効') : ''),
        h('td', {}, t.email), h('td', {}, t.ticket_type), h('td', {}, t.order_no || ''),
        h('td', {}, t.emailed_at ? fmtDateTime(t.emailed_at) : h('span', { class: 'chip warn' }, '未送信')),
        h('td', {}, t.checked_in_at ? h('span', { class: 'chip ok' }, `${fmtTime(t.checked_in_at)} ${t.gate || ''}`) : ''),
        h('td', { class: 'actions' },
          t.checked_in_at && h('button', { onclick: () => act('/api/undo', { id: t.id }, `${t.name} 様の入場記録を取り消しますか?`) }, '入場取消'),
          t.status === 'valid' && h('button', { onclick: () => act('/api/send', { ids: [t.id] }, `${t.email} にチケットを再送しますか?`) }, '再送'),
          t.status === 'valid'
            ? h('button', { class: 'danger', onclick: () => act('/api/cancel', { id: t.id }, `${t.name} 様のチケットを無効にしますか?(入場できなくなります)`) }, '無効化')
            : h('button', { onclick: () => act('/api/cancel', { id: t.id, restore: true }) }, '有効に戻す')))))),
  ];
}

// ===== 準備 =====
function toolsView() {
  const out = h('div', { class: 'muted', style: 'white-space:pre-wrap;font-size:14px' });
  const file = h('input', { type: 'file', accept: '.csv,text/csv' });
  const importBtn = h('button', {
    class: 'primary', onclick: async () => {
      const f = file.files[0];
      if (!f) return alert('CSVファイルを選んでください');
      const buf = await f.arrayBuffer();
      let csv;
      try { csv = new TextDecoder('utf-8', { fatal: true }).decode(buf); } catch { csv = new TextDecoder('shift_jis').decode(buf); }
      importBtn.disabled = true;
      try {
        const r = await api('/api/import', { method: 'POST', body: { csv }, timeout: 30000 });
        out.textContent = `チケットを ${r.created} 枚発行しました(登録済みのためスキップ: ${r.skipped} 枚)`;
        await load();
      } catch (e) { out.textContent = '取り込めませんでした:\n' + e.message; }
      finally { importBtn.disabled = false; }
    },
  }, '取り込む');
  const sendOut = h('div', { class: 'muted', style: 'white-space:pre-wrap;font-size:14px' });
  const sendBtn = h('button', {
    class: 'primary', disabled: !stats?.unsent, onclick: async () => {
      if (!confirm(`未送信の ${stats.unsent} 枚分のチケットメールを${stats.dryRun ? '作成(テスト)' : '送信'}しますか?`)) return;
      sendBtn.disabled = true; sendOut.textContent = '送信中…';
      try {
        const r = await api('/api/send', { method: 'POST', body: {}, timeout: 600000 });
        sendOut.textContent = `${r.emails} 通(チケット ${r.tickets} 枚分)を${r.dryRun ? 'outbox/ フォルダに保存' : '送信'}しました` +
          (r.failures.length ? `\n失敗 ${r.failures.length} 件:\n` + r.failures.map((f) => `${f.email}: ${f.error}`).join('\n') : '');
        await load();
      } catch (e) { sendOut.textContent = e.message; sendBtn.disabled = false; }
    },
  }, `未送信 ${stats?.unsent ?? '-'} 枚分を送る`);
  return [h('div', { class: 'tools' },
    h('div', { class: 'card' },
      h('h2', {}, '1. 参加者リストを取り込む'),
      h('p', {}, '1行目に見出しのあるCSV(Excelで保存したものもOK)。必須は「氏名」と「メールアドレス」です。同じファイルを2回取り込んでも二重発行はされません。'),
      h('pre', { class: 'code' }, '氏名,メールアドレス,券種,枚数,注文番号,備考\n山田 太郎,taro@example.com,一般,1,A-0001,\n佐藤 花子,hanako@example.com,一般,2,A-0002,同行者1名'),
      h('div', { class: 'row' }, h('div', { class: 'grow' }, file), importBtn), out),
    h('div', { class: 'card' },
      h('h2', {}, '2. チケットをメールで送る'),
      h('p', {}, stats?.dryRun
        ? 'いまはテストモード(SMTP未設定)です。メールは送らず、サーバーの outbox/ フォルダに保存されるので、見た目を確認できます。'
        : 'まだメールを送っていないチケットだけを送ります。同じ人の複数枚は1通にまとめます。'),
      sendBtn, sendOut),
    h('div', { class: 'card' },
      h('h2', {}, '3. 当日の準備'),
      h('p', {}, 'スタッフのスマホで下のURLを開き、スタッフ用パスワードでログインします。ホーム画面に追加しておくとアプリのように使えます。'),
      h('pre', { class: 'code' }, `${location.origin}/scan`),
      h('p', {}, '開場前に一度ログインしておけば、チケット一覧が端末に保存され、電波が切れても判定を続けられます(電波が戻ると自動で送信)。')))];
}
