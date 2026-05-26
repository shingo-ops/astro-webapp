#!/usr/bin/env node
/**
 * generate-adr-index.js
 *
 * docs/adr/ADR-*.md を走査して docs/adr/README.md を自動生成する。
 *
 * 使用方法:
 *   node scripts/generate-adr-index.js          # 生成（ファイル書き込み）
 *   node scripts/generate-adr-index.js --check  # 差分チェック（CI用・exit 1で失敗）
 */

'use strict';

const { readFileSync, writeFileSync, existsSync, readdirSync } = require('fs');
const { join, basename } = require('path');
const { execSync } = require('child_process');

const repoRoot = execSync('git rev-parse --show-toplevel', { encoding: 'utf8' }).trim();
const adrDir = join(repoRoot, 'docs/adr');
const outputPath = join(adrDir, 'README.md');
const checkMode = process.argv.includes('--check');

/** ADR ファイルからタイトル・ステータス・日付を抽出 */
function parseAdr(filePath) {
  const content = readFileSync(filePath, 'utf8');
  const lines = content.split('\n');

  // タイトル: 最初の # 見出し
  const titleLine = lines.find(l => l.startsWith('# '));
  const title = titleLine ? titleLine.replace(/^#\s+/, '').trim() : '(タイトル不明)';

  // ステータス抽出
  let status = '—';
  for (let i = 0; i < lines.length; i++) {
    const line = lines[i];
    // ## ステータス / ## Status の次行
    if (/^##\s+(?:ステータス|Status)\s*$/i.test(line)) {
      for (let j = i + 1; j < Math.min(i + 4, lines.length); j++) {
        const next = lines[j].replace(/[*_|]/g, '').trim();
        if (next && next.length > 0 && next.length < 50 && !/^-+$/.test(next)) {
          status = next; break;
        }
      }
      break;
    }
    // **ステータス:** / **Status:** インライン
    const inlineMatch = line.match(/\*\*(?:ステータス|Status)[：:]\*\*\s*(.+)/i);
    if (inlineMatch) { status = inlineMatch[1].replace(/[*_]/g, '').trim(); break; }
    // | ステータス | 値 | テーブル行
    const tableMatch = line.match(/\|\s*(?:ステータス|Status)\s*\|\s*([^|]+)\|/i);
    if (tableMatch) { status = tableMatch[1].trim(); break; }
  }

  // ステータス値の正規化
  const s = status.toLowerCase();
  if (/accept|承認|採択|完了|実装済|done/.test(s)) status = 'Accepted';
  else if (/propos|提案/.test(s)) status = 'Proposed';
  else if (/deprecat|廃止|非推奨/.test(s)) status = 'Deprecated';
  else if (/supersed|上書|置換/.test(s)) status = 'Superseded';

  // 日付抽出
  let date = '—';
  const datePatterns = [
    /\*\*日付[：:]\*\*\s*([\d]{4}-[\d]{2}-[\d]{2})/,
    /\*\*Date[：:]\*\*\s*([\d]{4}-[\d]{2}-[\d]{2})/i,
    /^- \*\*日付\*\*[：:]\s*([\d]{4}-[\d]{2}-[\d]{2})/,
    /\|\s*日付\s*\|\s*([\d]{4}-[\d]{2}-[\d]{2})/,
    /Date[：:]\s*([\d]{4}-[\d]{2}-[\d]{2})/i,
  ];
  for (const line of lines) {
    for (const pat of datePatterns) {
      const m = line.match(pat);
      if (m) { date = m[1]; break; }
    }
    if (date !== '—') break;
  }

  return { title, status, date };
}

/** ADR 番号を抽出（ソート用） */
function extractNumber(filename) {
  const m = basename(filename).match(/ADR-(\d+)/i);
  return m ? parseInt(m[1], 10) : 9999;
}

// ADR ファイル一覧を収集（README.md 自身を除く）
const files = readdirSync(adrDir)
  .filter(f => /^ADR-\d+.*\.md$/i.test(f) && f !== 'README.md')
  .sort((a, b) => {
    const na = extractNumber(a), nb = extractNumber(b);
    if (na !== nb) return na - nb;
    return a.localeCompare(b);
  });

// 各ファイルをパース
const rows = files.map(f => {
  const { title, status, date } = parseAdr(join(adrDir, f));
  const num = extractNumber(f);
  return { num, file: f, title, status, date };
});

// README.md 生成
const today = new Date().toISOString().slice(0, 10);
const tableRows = rows.map(r =>
  `| [ADR-${String(r.num).padStart(3, '0')}](./${r.file}) | ${r.title} | ${r.status} | ${r.date} |`
).join('\n');

const output = `# ADR インデックス

> このファイルは \`scripts/generate-adr-index.js\` により自動生成されます。
> **手動編集禁止。** ADR ファイルを追加・変更後に \`node scripts/generate-adr-index.js\` を実行してください。

最終更新: ${today} / ADR 総数: ${rows.length} 件

## 一覧

| 番号 | タイトル | ステータス | 日付 |
|------|---------|-----------|------|
${tableRows}

## ステータス凡例

| ステータス | 意味 |
|-----------|------|
| Accepted | 承認済み・有効 |
| Proposed | 提案中 / レビュー待ち |
| Deprecated | 非推奨（後継 ADR 参照） |
| Superseded | 別 ADR により上書き済み |
`;

if (checkMode) {
  if (!existsSync(outputPath)) {
    console.error('❌ docs/adr/README.md が存在しません。');
    console.error('   node scripts/generate-adr-index.js を実行して生成してください。');
    process.exit(1);
  }
  const current = readFileSync(outputPath, 'utf8');
  // 日付行を除いて比較
  const normalize = s => s.replace(/最終更新: \d{4}-\d{2}-\d{2}/, '最終更新: DATE');
  if (normalize(current) !== normalize(output)) {
    console.error('❌ docs/adr/README.md が最新の状態ではありません。');
    console.error('   ADR ファイルを追加・変更後は node scripts/generate-adr-index.js を実行してください。');
    process.exit(1);
  }
  console.log('✅ docs/adr/README.md は最新の状態です。');
  process.exit(0);
} else {
  writeFileSync(outputPath, output, 'utf8');
  console.log(`✅ docs/adr/README.md を生成しました（${rows.length} 件）`);
}
