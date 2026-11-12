import { test } from 'node:test';
import assert from 'node:assert/strict';
import { openDb, createTicket } from '../src/db.js';
import { makeCode, parseCode } from '../src/token.js';
import { checkIn, undoCheckIn } from '../src/checkin.js';
import { parseCsv, rowsToAttendees, decodeCsvBuffer } from '../src/csv.js';
import { importAttendees } from '../src/importer.js';
import { createApp } from '../src/app.js';

const SECRET = 'test-secret';

test('署名付きコード: 正しいものは通り、改ざんは弾く', () => {
  const code = makeCode('ABCDEFGHJK', SECRET);
  assert.deepEqual(parseCode(code, SECRET), { id: 'ABCDEFGHJK' });
  assert.equal(parseCode(code.slice(0, -1) + (code.at(-1) === 'A' ? 'B' : 'A'), SECRET).error, 'bad_signature');
  assert.equal(parseCode(makeCode('ABCDEFGHJK', 'other'), SECRET).error, 'bad_signature');
  assert.deepEqual(parseCode('abcde-fghjk', SECRET), { id: 'ABCDEFGHJK', manual: true });
  assert.equal(parseCode('hello', SECRET).error, 'unknown_format');
});

test('入場: 1回目OK、2回目は入場済み、取消後は再びOK', () => {
  const db = openDb(':memory:');
  const t = createTicket(db, { name: '山田', email: 'a@example.com' });
  const code = makeCode(t.id, SECRET);
  assert.equal(checkIn(db, SECRET, { input: code, gate: 'A' }).result, 'ok');
  const dup = checkIn(db, SECRET, { input: code, gate: 'B' });
  assert.equal(dup.result, 'duplicate');
  assert.equal(dup.ticket.gate, 'A');
  assert.ok(undoCheckIn(db, t.id));
  assert.equal(checkIn(db, SECRET, { input: t.id, gate: 'B' }).result, 'ok');
  const logs = db.prepare('SELECT result FROM checkin_logs ORDER BY id').all().map((r) => r.result);
  assert.deepEqual(logs, ['ok', 'duplicate', 'undo', 'ok']);
});

test('入場: 存在しない・キャンセル済み', () => {
  const db = openDb(':memory:');
  const t = createTicket(db, { name: '佐藤', email: 'b@example.com' });
  db.prepare(`UPDATE tickets SET status='cancelled' WHERE id=?`).run(t.id);
  assert.equal(checkIn(db, SECRET, { input: makeCode(t.id, SECRET) }).result, 'cancelled');
  assert.equal(checkIn(db, SECRET, { input: makeCode('ZZZZZZZZZZ', SECRET) }).result, 'invalid');
});

test('CSV: 日本語ヘッダー・枚数・Shift_JIS・再取込で二重発行しない', () => {
  const csv = '﻿氏名,メールアドレス,券種,枚数,注文番号\n山田 太郎,taro@example.com,一般,1,A-1\n"佐藤, 花子",hanako@example.com,VIP,2,A-2\n';
  const { attendees, errors } = rowsToAttendees(parseCsv(csv));
  assert.deepEqual(errors, []);
  assert.equal(attendees[1].name, '佐藤, 花子');
  const db = openDb(':memory:');
  assert.deepEqual(importAttendees(db, attendees), { created: 3, skipped: 0 });
  assert.deepEqual(importAttendees(db, attendees), { created: 0, skipped: 3 });

  const sjis = Buffer.from([0x8e, 0x81, 0x96, 0xbc]); // 「氏名」(Shift_JIS)
  assert.equal(decodeCsvBuffer(sjis), '氏名');

  const bad = rowsToAttendees(parseCsv('name,email\n,x@example.com\nA,not-an-email\n'));
  assert.equal(bad.errors.length, 2);
});

test('API: ログインなしは401、スタッフはスキャンできるが管理APIは不可', async () => {
  const db = openDb(':memory:');
  const config = { secret: SECRET, staffPassword: 'staff', adminPassword: 'admin', eventName: 'E', gates: ['A', 'B'] };
  const app = createApp({ db, config, mailer: { dryRun: true } });
  const server = app.listen(0);
  const base = `http://127.0.0.1:${server.address().port}`;
  try {
    const t = createTicket(db, { name: '鈴木', email: 'c@example.com' });
    let r = await fetch(`${base}/api/checkin`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}' });
    assert.equal(r.status, 401);

    r = await fetch(`${base}/api/login`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ password: 'staff' }) });
    const cookie = r.headers.get('set-cookie').split(';')[0];
    const post = (p, body) => fetch(`${base}${p}`, { method: 'POST', headers: { 'Content-Type': 'application/json', cookie }, body: JSON.stringify(body) });

    r = await post('/api/checkin', { input: makeCode(t.id, SECRET), gate: 'A' });
    assert.equal((await r.json()).result, 'ok');

    r = await post('/api/sync', { items: [{ local_id: 'x', input: t.id, gate: 'B', scanned_at: new Date().toISOString() }] });
    assert.equal((await r.json()).results[0].result, 'duplicate');

    r = await fetch(`${base}/api/stats`, { headers: { cookie } });
    assert.equal(r.status, 401);

    // 改ざんしたCookieは無効
    r = await fetch(`${base}/api/snapshot`, { headers: { cookie: cookie.replace('staff', 'admin') } });
    assert.equal(r.status, 401);
  } finally {
    server.close();
  }
});

test('メール: 同じ人の複数枚は1通にまとまり、本文にチケット番号とQRが入る', async () => {
  const fs = await import('node:fs');
  const os = await import('node:os');
  const path = await import('node:path');
  const { createMailer, sendPending } = await import('../src/mailer.js');
  const { formatId } = await import('../src/token.js');
  const cwd = process.cwd();
  const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'mail-'));
  process.chdir(tmp);
  try {
    const db = openDb(':memory:');
    importAttendees(db, [{ name: '佐藤', email: 'h@example.com', ticket_type: '一般', quantity: 2, order_no: 'A-2' }]);
    const mailer = createMailer({ secret: SECRET, smtp: {}, eventName: 'E', mailFrom: 'x@example.com' });
    const r = await sendPending(db, mailer);
    assert.equal(r.emails, 1);
    assert.equal(r.tickets, 2);
    const html = fs.readFileSync(path.join(tmp, 'outbox', fs.readdirSync(path.join(tmp, 'outbox')).find((f) => f.endsWith('.html'))), 'utf8');
    for (const t of db.prepare('SELECT id FROM tickets').all()) assert.ok(html.includes(formatId(t.id)));
    assert.equal((html.match(/data:image\/png;base64/g) || []).length, 2);
    assert.ok(!html.includes('${'));
    assert.equal(db.prepare('SELECT COUNT(*) n FROM tickets WHERE emailed_at IS NULL').get().n, 0);
  } finally {
    process.chdir(cwd);
    fs.rmSync(tmp, { recursive: true, force: true });
  }
});
