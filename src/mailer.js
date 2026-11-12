import fs from 'node:fs';
import path from 'node:path';
import nodemailer from 'nodemailer';
import QRCode from 'qrcode';
import { makeCode, formatId } from './token.js';

const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

export function createMailer(config) {
  const dryRun = !config.smtp.host;
  const transport = dryRun
    ? nodemailer.createTransport({ streamTransport: true, buffer: true, newline: 'unix' })
    : nodemailer.createTransport({
        host: config.smtp.host,
        port: config.smtp.port,
        secure: config.smtp.secure,
        auth: config.smtp.user ? { user: config.smtp.user, pass: config.smtp.pass } : undefined,
      });
  const outbox = path.resolve('outbox');

  // 同じ人(メールアドレス+注文番号)のチケットはまとめて1通で送る
  async function sendTickets(tickets) {
    const first = tickets[0];
    const items = [];
    const attachments = [];
    for (const t of tickets) {
      const code = makeCode(t.id, config.secret);
      const png = await QRCode.toBuffer(code, { width: 360, margin: 2, errorCorrectionLevel: 'M' });
      const cid = `qr-${t.id}@ticket`;
      attachments.push({ filename: `ticket-${t.id}.png`, content: png, cid, contentType: 'image/png' });
      items.push({ t, cid, png });
    }

    const subject = `【${config.eventName}】電子チケットのお届け${tickets.length > 1 ? `(${tickets.length}枚)` : ''}`;
    const ticketHtml = (imgSrc) => items.map(({ t, cid, png }, i) => `
      <div style="border:1px solid #ddd;border-radius:12px;padding:20px;margin:16px 0;text-align:center">
        <div style="font-size:14px;color:#666">チケット ${i + 1} / ${items.length}</div>
        <div style="font-size:18px;font-weight:bold;margin:4px 0">${esc(t.ticket_type)}</div>
        <img src="${imgSrc(cid, png)}" width="240" height="240" alt="入場用QRコード" style="display:block;margin:8px auto">
        <div style="font-family:monospace;font-size:20px;letter-spacing:2px">${formatId(t.id)}</div>
        <div style="font-size:12px;color:#666">チケット番号(QRが読めないときに使います)</div>
      </div>`).join('');
    const html = (imgSrc) => `<!doctype html><html><body style="font-family:sans-serif;max-width:520px;margin:0 auto;padding:16px;color:#222">
      <h2 style="margin:0 0 8px">${esc(config.eventName)}</h2>
      <p>${esc(first.name)} 様</p>
      <p>このたびはお申し込みありがとうございます。<br>当日は入場口でこのメールのQRコードをスタッフにご提示ください。</p>
      <table style="font-size:14px;margin:12px 0">
        ${config.eventDate ? `<tr><td style="color:#666;padding-right:12px">日時</td><td>${esc(config.eventDate)}</td></tr>` : ''}
        ${config.eventVenue ? `<tr><td style="color:#666;padding-right:12px">会場</td><td>${esc(config.eventVenue)}</td></tr>` : ''}
        ${first.order_no ? `<tr><td style="color:#666;padding-right:12px">注文番号</td><td>${esc(first.order_no)}</td></tr>` : ''}
      </table>
      ${ticketHtml(imgSrc)}
      <ul style="font-size:13px;color:#555;padding-left:18px">
        <li>QRコード1つにつき1名様が入場できます。${items.length > 1 ? '同行者の方には、該当するQRコードの画像を共有してください。' : ''}</li>
        <li>スクリーンショットや印刷したものでも入場できます。</li>
        <li>QRコードは最初に読み取られた1回のみ有効です。他の方に渡さないでください。</li>
      </ul>
    </body></html>`;

    const text = [
      `${config.eventName}`,
      `${first.name} 様`,
      '',
      '当日は入場口でこのメールのQRコードをご提示ください。',
      config.eventDate && `日時: ${config.eventDate}`,
      config.eventVenue && `会場: ${config.eventVenue}`,
      '',
      ...items.map(({ t }, i) => `チケット${i + 1}: ${t.ticket_type} / チケット番号 ${formatId(t.id)}`),
    ].filter((l) => typeof l === 'string').join('\n');

    const info = await transport.sendMail({
      from: config.mailFrom,
      to: first.email,
      subject,
      text,
      html: html((cid) => `cid:${cid}`),
      attachments,
    });

    if (dryRun) {
      // 送信せずに確認用ファイルを保存する
      fs.mkdirSync(outbox, { recursive: true });
      const base = path.join(outbox, `${first.id}`);
      fs.writeFileSync(`${base}.eml`, info.message);
      fs.writeFileSync(`${base}.html`, html((cid, png) => `data:image/png;base64,${png.toString('base64')}`));
    }
    return { dryRun };
  }

  return { sendTickets, dryRun };
}

// 未送信(または指定)のチケットをまとめて送る
export async function sendPending(db, mailer, { ids, onlyUnsent = true } = {}) {
  let rows;
  if (ids && ids.length) {
    rows = db.prepare(`SELECT * FROM tickets WHERE id IN (${ids.map(() => '?').join(',')}) AND status = 'valid'`).all(...ids);
  } else {
    rows = db.prepare(`SELECT * FROM tickets WHERE status = 'valid' ${onlyUnsent ? 'AND emailed_at IS NULL' : ''} ORDER BY created_at`).all();
  }
  const groups = new Map();
  for (const t of rows) {
    const key = `${t.email.toLowerCase()}|${t.order_no || ''}`;
    if (!groups.has(key)) groups.set(key, []);
    groups.get(key).push(t);
  }
  const mark = db.prepare(`UPDATE tickets SET emailed_at = ? WHERE id = ?`);
  let sent = 0;
  const failures = [];
  for (const group of groups.values()) {
    try {
      await mailer.sendTickets(group);
      const now = new Date().toISOString();
      for (const t of group) mark.run(now, t.id);
      sent++;
    } catch (e) {
      failures.push({ email: group[0].email, error: e.message });
    }
  }
  return { emails: sent, tickets: rows.length, failures, dryRun: mailer.dryRun };
}
