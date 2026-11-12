import crypto from 'node:crypto';

// QRコードの中身: "T1.<チケットID>.<署名>"
// チケットIDはランダムで推測できず、署名で改ざん・偽造を防ぐ。
const PREFIX = 'T1';
const ALPHABET = 'ABCDEFGHJKLMNPQRSTUVWXYZ23456789'; // 読み間違えやすい 0/O/1/I を除外

export function newTicketId() {
  // 10文字 × 32種 = 50bit。手入力もできる長さ。
  const bytes = crypto.randomBytes(10);
  let id = '';
  for (const b of bytes) id += ALPHABET[b % 32];
  return id;
}

function sign(id, secret) {
  return crypto.createHmac('sha256', secret).update(`${PREFIX}.${id}`).digest('base64url').slice(0, 16);
}

export function makeCode(id, secret) {
  return `${PREFIX}.${id}.${sign(id, secret)}`;
}

// 入力を正規化してチケットIDを取り出す。
// - QRの文字列 "T1.ID.SIG" → 署名を検証
// - 手入力の "ID"(ハイフン・空白・小文字も可) → IDのみ
// 戻り値: { id } または { error }
export function parseCode(input, secret) {
  const raw = String(input || '').trim();
  if (!raw) return { error: 'empty' };
  const parts = raw.split('.');
  if (parts.length === 3 && parts[0] === PREFIX) {
    const [, id, sig] = parts;
    const expected = sign(id, secret);
    const a = Buffer.from(sig);
    const b = Buffer.from(expected);
    if (a.length !== b.length || !crypto.timingSafeEqual(a, b)) return { error: 'bad_signature' };
    return { id };
  }
  const id = raw.toUpperCase().replace(/[\s-]/g, '');
  if (/^[A-Z0-9]{10}$/.test(id)) return { id, manual: true };
  return { error: 'unknown_format' };
}

// メールに載せる表示用(ABCDE-FGHJK)
export function formatId(id) {
  return `${id.slice(0, 5)}-${id.slice(5)}`;
}
