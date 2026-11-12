// 使い方: npm run send   (未送信のチケットだけ送ります)
import { config, assertConfig } from '../src/config.js';
import { openDb } from '../src/db.js';
import { createMailer, sendPending } from '../src/mailer.js';

assertConfig();
const db = openDb(config.dbPath);
const mailer = createMailer(config);
const r = await sendPending(db, mailer);
console.log(`${r.emails} 通のメール(チケット ${r.tickets} 枚分)を${r.dryRun ? ' outbox/ に保存' : '送信'}しました`);
for (const f of r.failures) console.error(`  送信失敗: ${f.email} — ${f.error}`);
if (r.failures.length) process.exit(1);
