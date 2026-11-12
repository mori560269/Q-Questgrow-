import { config, assertConfig } from './config.js';
import { openDb } from './db.js';
import { createMailer } from './mailer.js';
import { createApp } from './app.js';

assertConfig();
const db = openDb(config.dbPath);
const mailer = createMailer(config);
const app = createApp({ db, config, mailer });

app.listen(config.port, () => {
  console.log(`入場チェックシステム起動: http://localhost:${config.port}`);
  console.log(`  スキャン画面: http://localhost:${config.port}/scan`);
  console.log(`  管理画面:     http://localhost:${config.port}/admin`);
  if (mailer.dryRun) console.log('  ※ SMTP未設定のため、メールは送信せず outbox/ に保存します');
});
