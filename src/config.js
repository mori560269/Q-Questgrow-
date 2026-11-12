import fs from 'node:fs';
import path from 'node:path';

// .env を読み込む(依存パッケージなしの簡易版)
const envPath = path.resolve(process.cwd(), '.env');
if (fs.existsSync(envPath)) {
  for (const line of fs.readFileSync(envPath, 'utf8').split(/\r?\n/)) {
    const m = line.match(/^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)\s*$/);
    if (!m || line.trim().startsWith('#')) continue;
    let v = m[2];
    if ((v.startsWith('"') && v.endsWith('"')) || (v.startsWith("'") && v.endsWith("'"))) v = v.slice(1, -1);
    if (process.env[m[1]] === undefined) process.env[m[1]] = v;
  }
}

const env = process.env;

export const config = {
  secret: env.SECRET || '',
  staffPassword: env.STAFF_PASSWORD || '',
  adminPassword: env.ADMIN_PASSWORD || '',
  eventName: env.EVENT_NAME || 'イベント',
  eventDate: env.EVENT_DATE || '',
  eventVenue: env.EVENT_VENUE || '',
  gates: (env.GATES || 'ゲートA,ゲートB').split(',').map((s) => s.trim()).filter(Boolean),
  smtp: {
    host: env.SMTP_HOST || '',
    port: Number(env.SMTP_PORT || 587),
    secure: env.SMTP_SECURE === 'true',
    user: env.SMTP_USER || '',
    pass: env.SMTP_PASS || '',
  },
  mailFrom: env.MAIL_FROM || 'ticket@example.com',
  port: Number(env.PORT || 3000),
  dbPath: env.DB_PATH || './data/checkin.db',
};

export function assertConfig() {
  const missing = [];
  if (!config.secret || config.secret === 'change-me-to-a-long-random-string') missing.push('SECRET');
  if (!config.staffPassword) missing.push('STAFF_PASSWORD');
  if (!config.adminPassword) missing.push('ADMIN_PASSWORD');
  if (missing.length) {
    console.error(`設定が足りません: ${missing.join(', ')} を .env に設定してください(.env.example を参照)`);
    process.exit(1);
  }
}
