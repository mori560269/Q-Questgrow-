import { createTicket } from './db.js';

// 参加者リストからチケットを作る。
// 同じCSVを2回読み込んでも二重発行しないよう、
// 「注文番号」または「氏名+メール+券種」が同じものは既存の枚数を差し引く。
export function importAttendees(db, attendees) {
  let created = 0;
  let skipped = 0;
  const countStmt = db.prepare(
    `SELECT COUNT(*) AS n FROM tickets WHERE name = ? AND email = ? AND ticket_type = ? AND COALESCE(order_no, '') = ?`
  );
  db.exec('BEGIN');
  try {
    for (const a of attendees) {
      const existing = countStmt.get(a.name, a.email, a.ticket_type, a.order_no || '').n;
      const need = Math.max(0, a.quantity - existing);
      skipped += a.quantity - need;
      for (let i = 0; i < need; i++) {
        createTicket(db, a);
        created++;
      }
    }
    db.exec('COMMIT');
  } catch (e) {
    db.exec('ROLLBACK');
    throw e;
  }
  return { created, skipped };
}
