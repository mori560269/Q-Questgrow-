// 小さな CSV パーサー(ダブルクォート・改行入りセル対応)
export function parseCsv(text) {
  text = text.replace(/^﻿/, '');
  const rows = [];
  let row = [];
  let cell = '';
  let q = false;
  for (let i = 0; i < text.length; i++) {
    const c = text[i];
    if (q) {
      if (c === '"') {
        if (text[i + 1] === '"') { cell += '"'; i++; } else q = false;
      } else cell += c;
    } else if (c === '"') q = true;
    else if (c === ',') { row.push(cell); cell = ''; }
    else if (c === '\n' || c === '\r') {
      if (c === '\r' && text[i + 1] === '\n') i++;
      row.push(cell); rows.push(row); row = []; cell = '';
    } else cell += c;
  }
  if (cell !== '' || row.length) { row.push(cell); rows.push(row); }
  return rows.filter((r) => r.some((c) => c.trim() !== ''));
}

export function toCsv(rows) {
  return rows
    .map((r) => r.map((v) => {
      const s = v == null ? '' : String(v);
      return /[",\r\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
    }).join(','))
    .join('\r\n');
}

// UTF-8 / Shift_JIS(Excelで保存したCSV)を自動判別して文字列にする
export function decodeCsvBuffer(buf) {
  try {
    return new TextDecoder('utf-8', { fatal: true }).decode(buf);
  } catch {
    return new TextDecoder('shift_jis').decode(buf);
  }
}

const HEADER_ALIASES = {
  name: ['name', '氏名', '名前', 'お名前'],
  email: ['email', 'mail', 'メール', 'メールアドレス', 'e-mail'],
  ticket_type: ['ticket_type', 'type', '券種', 'チケット種別', '種別'],
  quantity: ['quantity', 'qty', '枚数'],
  order_no: ['order_no', 'order', '注文番号', '申込番号'],
  note: ['note', '備考', 'メモ'],
};

// CSV の行を参加者データに変換する。1行目はヘッダー。
export function rowsToAttendees(rows) {
  if (rows.length < 2) return { attendees: [], errors: ['データ行がありません(1行目はヘッダーにしてください)'] };
  const header = rows[0].map((h) => h.trim().toLowerCase());
  const idx = {};
  for (const [key, aliases] of Object.entries(HEADER_ALIASES)) {
    idx[key] = header.findIndex((h) => aliases.includes(h));
  }
  const errors = [];
  if (idx.name < 0) errors.push('「name(氏名)」列が見つかりません');
  if (idx.email < 0) errors.push('「email(メールアドレス)」列が見つかりません');
  if (errors.length) return { attendees: [], errors };

  const attendees = [];
  rows.slice(1).forEach((r, i) => {
    const get = (k) => (idx[k] >= 0 ? (r[idx[k]] || '').trim() : '');
    const line = i + 2;
    const name = get('name');
    const email = get('email');
    const qty = get('quantity') ? Number(get('quantity')) : 1;
    if (!name) return errors.push(`${line}行目: 氏名が空です`);
    if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)) return errors.push(`${line}行目: メールアドレスが不正です (${email})`);
    if (!Number.isInteger(qty) || qty < 1 || qty > 20) return errors.push(`${line}行目: 枚数が不正です (${get('quantity')})`);
    attendees.push({ name, email, ticket_type: get('ticket_type') || '一般', quantity: qty, order_no: get('order_no'), note: get('note') });
  });
  return { attendees, errors };
}
