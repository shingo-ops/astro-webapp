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

// 検出パターン
// ※ var() / calc() を含む値はプロパティ名ごとに個別にスキップする（下記の行単位スキップは廃止）
const PATTERNS = [
  {
    name: 'opacity',
    // 0.1 〜 0.9x の中間値のみ検出（0 / 1 は完全非表示/表示の機能値として許可）
    regex: /opacity\s*:\s*0\.[1-9]\d*/,
    message: '→ CSS変数を使ってください: var(--opacity-xxx)（ADR-067）',
  },
  {
    name: 'border-radius-px',
    // border-radius: 3px, border-radius: 10px 等を検出（var/calc を含む場合はスキップ）
    regex: /border-radius\s*:(?![^;]*(?:var|calc)\()[^;]*\d+(?:\.\d+)?px/,
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
  {
    name: 'spacing-px',
    // padding/margin/gap に生px値（≥4px）を直書きした場合を検出
    // var()/calc() を含む値はスキップ（既にCSS式使用済み）
    // 除外: 0/1px/2px/3px（ボーダー等の構造的値）
    regex: /(?:padding|margin|gap|row-gap|column-gap)\s*:(?![^;]*(?:var|calc)\()[^;]*\b(?:[4-9]|\d{2,})\d*px/,
    message: '→ CSS変数を使ってください: var(--space-xxx)（ADR-067）',
  },
  {
    name: 'sizing-px',
    // width/height/min-*/max-* に生px値（≥4px）を直書きした場合を検出
    // var()/calc() を含む値はスキップ
    // (?<![a-zA-Z-]) で border-width / outline-width 等の誤検出を防ぐ（負の後読み）
    regex: /(?<![a-zA-Z-])(?:width|height|min-width|max-width|min-height|max-height)\s*:(?![^;]*(?:var|calc)\()[^;]*\b(?:[4-9]|\d{2,})\d*px/,
    message: '→ CSS変数を使ってください: var(--size-xxx) または var(--space-xxx)（ADR-067）',
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
  let inBlockComment = false;

  lines.forEach((line, i) => {
    const trimmed = line.trim();

    // ブロックコメント開始/終了をトラッキング
    if (inBlockComment) {
      if (trimmed.includes('*/')) inBlockComment = false;
      return; // ブロックコメント内はスキップ
    }
    if (trimmed.startsWith('/*')) {
      if (!trimmed.includes('*/')) inBlockComment = true; // 複数行コメント開始
      return;
    }

    // 行コメントはスキップ
    if (trimmed.startsWith('*') || trimmed.startsWith('//')) return;

    // CSS変数定義行はスキップ（--xxx: 値定義）
    if (trimmed.startsWith('--')) return;

    // @media クエリ行はスキップ（ブレークポイント数値 768px 等）
    if (trimmed.startsWith('@media') || trimmed.startsWith('@keyframes')) return;

    // var()/calc() を含む行のスキップは廃止。
    // 各パターンが (?![^;]*(?:var|calc)\() でプロパティ値ごとに個別判定する。

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
