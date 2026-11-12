// 使い方: npm run import -- attendees.csv
import fs from 'node:fs';
import { config, assertConfig } from '../src/config.js';
import { openDb } from '../src/db.js';
import { parseCsv, rowsToAttendees, decodeCsvBuffer } from '../src/csv.js';
import { importAttendees } from '../src/importer.js';

assertConfig();
const file = process.argv[2];
if (!file) {
  console.error('使い方: npm run import -- 参加者リスト.csv');
  process.exit(1);
}
const { attendees, errors } = rowsToAttendees(parseCsv(decodeCsvBuffer(fs.readFileSync(file))));
if (errors.length) {
  console.error('CSVにエラーがあります。何も登録していません:');
  for (const e of errors) console.error('  - ' + e);
  process.exit(1);
}
const db = openDb(config.dbPath);
const { created, skipped } = importAttendees(db, attendees);
console.log(`チケットを ${created} 枚発行しました(登録済みのためスキップ: ${skipped} 枚)`);
