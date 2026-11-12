import fs from 'node:fs';
import path from 'node:path';
import { DatabaseSync } from 'node:sqlite';
import { newTicketId } from './token.js';

export function openDb(dbPath) {
  if (dbPath !== ':memory:') fs.mkdirSync(path.dirname(path.resolve(dbPath)), { recursive: true });
  const db = new DatabaseSync(dbPath);
  db.exec(`
    PRAGMA journal_mode = WAL;
    PRAGMA busy_timeout = 5000;

    CREATE TABLE IF NOT EXISTS tickets (
      id            TEXT PRIMARY KEY,
      name          TEXT NOT NULL,
      email         TEXT NOT NULL,
      ticket_type   TEXT NOT NULL DEFAULT '一般',
      order_no      TEXT,
      note          TEXT,
      status        TEXT NOT NULL DEFAULT 'valid',   -- valid / cancelled
      emailed_at    TEXT,
      checked_in_at TEXT,
      gate          TEXT,
      created_at    TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
    );
    CREATE INDEX IF NOT EXISTS idx_tickets_email ON tickets(email);

    CREATE TABLE IF NOT EXISTS checkin_logs (
      id         INTEGER PRIMARY KEY AUTOINCREMENT,
      ticket_id  TEXT,
      input      TEXT,
      result     TEXT NOT NULL,   -- ok / duplicate / invalid / cancelled / undo
      gate       TEXT,
      device     TEXT,
      offline    INTEGER NOT NULL DEFAULT 0,
      scanned_at TEXT NOT NULL,
      logged_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
    );
    CREATE INDEX IF NOT EXISTS idx_logs_ticket ON checkin_logs(ticket_id);
  `);
  return db;
}

export function createTicket(db, { name, email, ticket_type, order_no, note }) {
  const id = newTicketId();
  db.prepare(
    `INSERT INTO tickets (id, name, email, ticket_type, order_no, note) VALUES (?, ?, ?, ?, ?, ?)`
  ).run(id, name, email, ticket_type || '一般', order_no || null, note || null);
  return getTicket(db, id);
}

export function getTicket(db, id) {
  return db.prepare(`SELECT * FROM tickets WHERE id = ?`).get(id) || null;
}

export function log(db, { ticket_id = null, input = null, result, gate = null, device = null, offline = false, scanned_at }) {
  db.prepare(
    `INSERT INTO checkin_logs (ticket_id, input, result, gate, device, offline, scanned_at) VALUES (?, ?, ?, ?, ?, ?, ?)`
  ).run(ticket_id, input, result, gate, device, offline ? 1 : 0, scanned_at || new Date().toISOString());
}
