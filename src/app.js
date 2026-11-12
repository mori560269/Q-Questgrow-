import crypto from 'node:crypto';
import path from 'node:path';
import express from 'express';
import { checkIn, undoCheckIn, publicTicket } from './checkin.js';
import { getTicket, log } from './db.js';
import { parseCsv, rowsToAttendees, toCsv } from './csv.js';
import { importAttendees } from './importer.js';
import { sendPending } from './mailer.js';
import { formatId } from './token.js';

const ROOT = path.resolve(import.meta.dirname, '..');
const SESSION_HOURS = 24;

export function createApp({ db, config, mailer }) {
  const app = express();
  app.disable('x-powered-by');
  app.use(express.json({ limit: '5mb' }));

  // ---------- 認証(署名付きCookie) ----------
  const signSession = (role, exp) => {
    const body = `${role}.${exp}`;
    return `${body}.${crypto.createHmac('sha256', config.secret).update(`session.${body}`).digest('base64url')}`;
  };
  const readSession = (req) => {
    const m = (req.headers.cookie || '').match(/(?:^|;\s*)sess=([^;]+)/);
    if (!m) return null;
    const [role, exp, sig] = decodeURIComponent(m[1]).split('.');
    if (!role || !exp || !sig) return null;
    const expected = signSession(role, exp).split('.')[2];
    if (sig.length !== expected.length || !crypto.timingSafeEqual(Buffer.from(sig), Buffer.from(expected))) return null;
    if (Date.now() > Number(exp)) return null;
    return role;
  };
  const need = (...roles) => (req, res, next) => {
    const role = readSession(req);
    if (!role || !roles.includes(role)) return res.status(401).json({ error: 'ログインしてください' });
    req.role = role;
    next();
  };
  const staff = need('staff', 'admin');
  const admin = need('admin');

  const safeEq = (a, b) => {
    const x = crypto.createHash('sha256').update(String(a)).digest();
    const y = crypto.createHash('sha256').update(String(b)).digest();
    return crypto.timingSafeEqual(x, y);
  };

  app.post('/api/login', async (req, res) => {
    const pw = String(req.body?.password || '');
    let role = null;
    if (safeEq(pw, config.adminPassword)) role = 'admin';
    else if (safeEq(pw, config.staffPassword)) role = 'staff';
    if (!role) {
      await new Promise((r) => setTimeout(r, 800)); // 総当たり対策
      return res.status(401).json({ error: 'パスワードが違います' });
    }
    const exp = Date.now() + SESSION_HOURS * 3600 * 1000;
    const secure = req.secure || req.headers['x-forwarded-proto'] === 'https' ? '; Secure' : '';
    res.setHeader('Set-Cookie', `sess=${encodeURIComponent(signSession(role, exp))}; Path=/; HttpOnly; SameSite=Strict; Max-Age=${SESSION_HOURS * 3600}${secure}`);
    res.json({ role });
  });

  app.post('/api/logout', (req, res) => {
    res.setHeader('Set-Cookie', 'sess=; Path=/; HttpOnly; SameSite=Strict; Max-Age=0');
    res.json({ ok: true });
  });

  app.get('/api/me', (req, res) => {
    res.json({ role: readSession(req), eventName: config.eventName, gates: config.gates });
  });

  // ---------- スキャン(スタッフ) ----------
  app.post('/api/checkin', staff, (req, res) => {
    const { input, gate, device } = req.body || {};
    res.json(checkIn(db, config.secret, { input, gate, device }));
  });

  // オフライン中にためたスキャンをまとめて送る
  app.post('/api/sync', staff, (req, res) => {
    const items = Array.isArray(req.body?.items) ? req.body.items.slice(0, 2000) : [];
    const results = items.map((it) => ({
      local_id: it.local_id,
      ...checkIn(db, config.secret, {
        input: it.input,
        gate: it.gate,
        device: it.device,
        scanned_at: typeof it.scanned_at === 'string' ? it.scanned_at : undefined,
        offline: true,
      }),
    }));
    res.json({ results });
  });

  // オフライン判定用のチケット一覧(IDと入場状態だけ)
  app.get('/api/snapshot', staff, (req, res) => {
    const rows = db.prepare(`SELECT id, name, ticket_type, status, checked_in_at, gate FROM tickets`).all();
    res.json({ at: new Date().toISOString(), tickets: rows });
  });

  // 手動受付用の検索(氏名・メール・注文番号・チケット番号)
  app.get('/api/search', staff, (req, res) => {
    const q = String(req.query.q || '').trim();
    if (q.length < 2) return res.json({ tickets: [] });
    const like = `%${q.replace(/[%_]/g, (c) => `\\${c}`)}%`;
    const idq = q.toUpperCase().replace(/[\s-]/g, '');
    const rows = db.prepare(
      `SELECT * FROM tickets WHERE name LIKE ? ESCAPE '\\' OR email LIKE ? ESCAPE '\\' OR order_no LIKE ? ESCAPE '\\' OR id = ?
       ORDER BY name LIMIT 30`
    ).all(like, like, like, idq);
    res.json({ tickets: rows.map((t) => ({ ...publicTicket(t), email: req.role === 'admin' ? t.email : maskEmail(t.email) })) });
  });

  // ---------- 管理 ----------
  app.get('/api/stats', admin, (req, res) => {
    const total = db.prepare(`SELECT COUNT(*) n FROM tickets WHERE status = 'valid'`).get().n;
    const checked = db.prepare(`SELECT COUNT(*) n FROM tickets WHERE status = 'valid' AND checked_in_at IS NOT NULL`).get().n;
    const unsent = db.prepare(`SELECT COUNT(*) n FROM tickets WHERE status = 'valid' AND emailed_at IS NULL`).get().n;
    const byGate = db.prepare(`SELECT gate, COUNT(*) n FROM tickets WHERE checked_in_at IS NOT NULL GROUP BY gate ORDER BY gate`).all();
    const byType = db.prepare(
      `SELECT ticket_type, COUNT(*) total, SUM(checked_in_at IS NOT NULL) checked FROM tickets WHERE status = 'valid' GROUP BY ticket_type ORDER BY ticket_type`
    ).all();
    const times = db.prepare(`SELECT checked_in_at FROM tickets WHERE checked_in_at IS NOT NULL`).all().map((r) => r.checked_in_at);
    const problems = db.prepare(`SELECT result, COUNT(*) n FROM checkin_logs WHERE result IN ('duplicate','invalid','cancelled') GROUP BY result`).all();
    const recent = db.prepare(
      `SELECT l.*, t.name, t.ticket_type FROM checkin_logs l LEFT JOIN tickets t ON t.id = l.ticket_id ORDER BY l.id DESC LIMIT 50`
    ).all();
    res.json({ total, checked, unsent, byGate, byType, times, problems, recent, dryRun: mailer.dryRun });
  });

  app.get('/api/tickets', admin, (req, res) => {
    res.json({ tickets: db.prepare(`SELECT * FROM tickets ORDER BY created_at, name`).all() });
  });

  app.post('/api/import', admin, (req, res) => {
    const { attendees, errors } = rowsToAttendees(parseCsv(String(req.body?.csv || '')));
    if (errors.length) return res.status(400).json({ errors });
    res.json(importAttendees(db, attendees));
  });

  app.post('/api/send', admin, async (req, res) => {
    const ids = Array.isArray(req.body?.ids) ? req.body.ids : undefined;
    res.json(await sendPending(db, mailer, { ids, onlyUnsent: !ids }));
  });

  app.post('/api/undo', admin, (req, res) => {
    res.json({ ok: undoCheckIn(db, String(req.body?.id || ''), { device: 'admin' }) });
  });

  app.post('/api/cancel', admin, (req, res) => {
    const id = String(req.body?.id || '');
    const status = req.body?.restore ? 'valid' : 'cancelled';
    const r = db.prepare(`UPDATE tickets SET status = ? WHERE id = ?`).run(status, id);
    if (r.changes) log(db, { ticket_id: id, result: status === 'valid' ? 'restore' : 'cancel', device: 'admin' });
    res.json({ ok: r.changes === 1, ticket: getTicket(db, id) });
  });

  app.get('/api/export.csv', admin, (req, res) => {
    const rows = db.prepare(`SELECT * FROM tickets ORDER BY name`).all();
    const csv = toCsv([
      ['チケット番号', '氏名', 'メール', '券種', '注文番号', '備考', '状態', 'メール送信', '入場時刻', 'ゲート'],
      ...rows.map((t) => [formatId(t.id), t.name, t.email, t.ticket_type, t.order_no, t.note, t.status === 'valid' ? '有効' : 'キャンセル', t.emailed_at, t.checked_in_at, t.gate]),
    ]);
    res.setHeader('Content-Type', 'text/csv; charset=utf-8');
    res.setHeader('Content-Disposition', `attachment; filename="checkin-${new Date().toISOString().slice(0, 10)}.csv"`);
    res.send('﻿' + csv); // BOM付きでExcelでも文字化けしない
  });

  // ---------- 画面 ----------
  app.get('/vendor/html5-qrcode.min.js', (req, res) => res.sendFile(path.join(ROOT, 'node_modules/html5-qrcode/html5-qrcode.min.js')));
  app.get('/', (req, res) => res.redirect('/scan.html'));
  app.use(express.static(path.join(ROOT, 'public'), { extensions: ['html'] }));

  app.use((err, req, res, _next) => {
    console.error(err);
    res.status(500).json({ error: 'サーバーエラーが発生しました' });
  });

  return app;
}

function maskEmail(e) {
  const [u, d] = String(e).split('@');
  return `${u.slice(0, 2)}***@${d || ''}`;
}
