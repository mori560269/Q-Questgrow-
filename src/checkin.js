import { parseCode } from './token.js';
import { getTicket, log } from './db.js';

// 1回のスキャンを処理する。結果は ok / duplicate / invalid / cancelled のいずれか。
// 「最初に読まれた1回だけ有効」を、条件付き UPDATE で原子的に判定する。
export function checkIn(db, secret, { input, gate, device, scanned_at, offline = false }) {
  const at = scanned_at || new Date().toISOString();
  const base = { input: String(input || '').slice(0, 200), gate, device, offline, scanned_at: at };

  const parsed = parseCode(input, secret);
  if (parsed.error) {
    log(db, { ...base, result: 'invalid' });
    return { result: 'invalid', reason: parsed.error === 'bad_signature' ? '偽造または壊れたQRです' : '読み取れない形式です' };
  }

  const ticket = getTicket(db, parsed.id);
  if (!ticket) {
    log(db, { ...base, ticket_id: parsed.id, result: 'invalid' });
    return { result: 'invalid', reason: '存在しないチケットです' };
  }
  if (ticket.status === 'cancelled') {
    log(db, { ...base, ticket_id: ticket.id, result: 'cancelled' });
    return { result: 'cancelled', reason: 'キャンセル済みのチケットです', ticket: publicTicket(ticket) };
  }

  const r = db
    .prepare(`UPDATE tickets SET checked_in_at = ?, gate = ? WHERE id = ? AND checked_in_at IS NULL AND status = 'valid'`)
    .run(at, gate || null, ticket.id);

  const latest = getTicket(db, ticket.id);
  if (r.changes === 1) {
    log(db, { ...base, ticket_id: ticket.id, result: 'ok' });
    return { result: 'ok', ticket: publicTicket(latest) };
  }
  log(db, { ...base, ticket_id: ticket.id, result: 'duplicate' });
  return { result: 'duplicate', reason: '入場済みのチケットです', ticket: publicTicket(latest) };
}

// 誤って入場処理したときの取り消し(管理者のみ)
export function undoCheckIn(db, id, { device } = {}) {
  const t = getTicket(db, id);
  if (!t || !t.checked_in_at) return false;
  db.prepare(`UPDATE tickets SET checked_in_at = NULL, gate = NULL WHERE id = ?`).run(id);
  log(db, { ticket_id: id, result: 'undo', device, gate: t.gate });
  return true;
}

export function publicTicket(t) {
  return {
    id: t.id,
    name: t.name,
    ticket_type: t.ticket_type,
    order_no: t.order_no,
    note: t.note,
    status: t.status,
    checked_in_at: t.checked_in_at,
    gate: t.gate,
  };
}
