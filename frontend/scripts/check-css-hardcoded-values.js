#!/usr/bin/env node
/**
 * check-css-hardcoded-values.js (ADR-067)
 *
 * CSS ファイル内の数値ハードコード（opacity / border-radius / z-index / animation duration）
 * を検出する。デザイントークン（CSS Custom Properties）への置換を強制する。
 *
 * 除外ファイル: tokens.css, index.css（変数定義ファイル）
 * 除外行: コメント行, CSS変数定義行（--xxx:）, @mediaクエリ行
 *
 * 使用方法: node scripts/check-css-hardcoded-values.js
 * CI: npm run check:css-values
 */

import { readFileSync, readdirSync, statSync } from 'fs';
import { join, extname, basename, relative, dirname } from 'path';
import { fileURLToPath } from 'url';

const __dirname = dirname(fileURLToPath(import.meta.url));
const SRC_DIR = join(__dirname, '../src');

// 変数定義ファイルは除外（値定義として数値が書かれる）
const EXCLUDE_FILES = new Set(['index.css', 'tokens.css']);

// 検出パターン: var() を含まない行のみ対象
const PATTERNS = [
  {
    name: 'opacity',
    // 0.1 〜 0.9x の中間値のみ検出（0 / 1 は完全非表示/表示の機能値として許可）
    regex: /opacity\s*:\s*0\.[1-9]\d*/,
    message: '→ CSS変数を使ってください: var(--opacity-xxx)（ADR-067）',
  },
  {
    name: 'border-radius-px',
    // border-radius: 3px, border-radius: 10px 等を検出
    regex: /border-radius\s*:\s*\d+(?:\.\d+)?px/,
    message: '→ CSS変数を使ってください: var(--radius-xxx)（ADR-067）',
  },
  {
    name: 'z-index',
    // z-index: 50, z-index: 100 等を検出
    regex: /z-index\s*:\s*\d+/,
    message: '→ CSS変数を使ってください: var(--z-xxx)（ADR-067）',
  },
  {
    name: 'animation-duration',
    // animation: fadeIn 200ms, animation-duration: 200ms 等を検出
    regex: /(?:animation(?:-duration)?)\s*:[^;]*\d+ms/,
    message: '→ CSS変数を使ってください: var(--transition-xxx) または var(--duration-base)（ADR-067）',
  },
];

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

const cssFiles = collectCssFiles(SRC_DIR).filter(
  (f) => !EXCLUDE_FILES.has(basename(f))
);

let hasError = false;

for (const file of cssFiles) {
  const lines = readFileSync(file, 'utf8').split('\n');
  lines.forEach((line, i) => {
    const trimmed = line.trim();

    // コメント行はスキップ
    if (
      trimmed.startsWith('/*') ||
      trimmed.startsWith('*') ||
      trimmed.startsWith('//')
    )
      return;

    // CSS変数定義行はスキップ（--xxx: 値定義）
    if (trimmed.startsWith('--')) return;

    // @media クエリ行はスキップ（ブレークポイント数値 768px 等）
    if (trimmed.startsWith('@media') || trimmed.startsWith('@keyframes')) return;

    // var() を含む行はスキップ（既にトークン参照済み）
    if (trimmed.includes('var(')) return;

    for (const { name, regex, message } of PATTERNS) {
      if (regex.test(trimmed)) {
        const rel = relative(process.cwd(), file);
        console.error(`❌ ${rel}:${i + 1} [${name}]`);
        console.error(`   ${trimmed}`);
        console.error(`   ${message}`);
        hasError = true;
        break; // 1行に複数マッチしても1件として扱う
      }
    }
  });
}

if (hasError) {
  console.error('');
  console.error(
    '❌ CSS数値ハードコードチェック FAILED: デザイントークン（CSS変数）を使用してください'
  );
  process.exit(1);
} else {
  console.log('✅ CSS数値ハードコードチェック PASSED');
  process.exit(0);
}
