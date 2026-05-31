#!/usr/bin/env node
/**
 * check-css-class-naming.js (ADR-087)
 *
 * hub-shell.css 共通化後に mc-* / crm-* シェルクラスが
 * 新規定義・再定義されていないかを検査する。
 *
 * 対象: src/ 以下の全 .css ファイル
 * 除外: hub-shell.css（正規の定義ファイル）
 *
 * 使用方法: node scripts/check-css-class-naming.js
 * CI: npm run check:css-class-naming
 */

import { readFileSync, readdirSync, statSync } from 'fs';
import { join, extname, basename, relative, dirname } from 'path';
import { fileURLToPath } from 'url';

const __dirname = dirname(fileURLToPath(import.meta.url));
const SRC_DIR = join(__dirname, '../src');

// 廃止クラスセレクタ（hub-shell.css に統合済み）
const BANNED_SELECTORS = [
  '.mc-shell',
  '.mc-subnav',
  '.mc-subnav-section',
  '.mc-subnav-title',
  '.mc-subnav-item',
  '.mc-content',
  '.crm-shell',
  '.crm-subnav',
  '.crm-subnav-item',
  '.crm-content',
];

// CSS セレクタとして使われているか判定する正規表現
// ルール定義（{ の前）またはコンビネーター（スペース、>、+、~ の前）として出現した場合に検出
function buildPattern(selector) {
  // エスケープして正規表現に変換
  const escaped = selector.replace('.', '\\.');
  // セレクタとして使われているパターン: `.mc-shell` の後ろが {, :, ,, スペース, >, +, ~ のいずれか
  return new RegExp(escaped + '(?=[\\s{:,>+~]|$)');
}

const BANNED_PATTERNS = BANNED_SELECTORS.map((s) => ({
  selector: s,
  pattern: buildPattern(s),
}));

function collectCssFiles(dir) {
  const results = [];
  for (const entry of readdirSync(dir)) {
    const full = join(dir, entry);
    if (statSync(full).isDirectory()) {
      results.push(...collectCssFiles(full));
    } else if (extname(entry) === '.css') {
      results.push(full);
    }
  }
  return results;
}

const files = collectCssFiles(SRC_DIR).filter(
  (f) => basename(f) !== 'hub-shell.css'
);

let errors = 0;

for (const file of files) {
  const rel = relative(SRC_DIR, file);
  const lines = readFileSync(file, 'utf8').split('\n');

  for (let i = 0; i < lines.length; i++) {
    const line = lines[i];
    // コメント行はスキップ
    if (/^\s*\/[/*]/.test(line)) continue;

    for (const { selector, pattern } of BANNED_PATTERNS) {
      if (pattern.test(line)) {
        console.error(
          `[css-class-naming] ${rel}:${i + 1} — "${selector}" は廃止クラスです。hub-subnav / hub-shell 等 hub-* クラスを使用してください。`
        );
        errors++;
      }
    }
  }
}

if (errors > 0) {
  console.error(`\n❌ ${errors} 件の廃止クラス使用を検出しました。`);
  console.error(
    '   hub-shell.css の hub-* クラスに置き換えてください。'
  );
  console.error('   詳細: docs/adr/ADR-087-hub-shell-layout-standard.md\n');
  process.exit(1);
}

console.log(`✅ css-class-naming: 廃止クラス (mc-*/crm-* shell) の使用なし`);
