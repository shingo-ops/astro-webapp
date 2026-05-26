#!/usr/bin/env node
/**
 * check-css-hardcoded-colors.js (ADR-067)
 *
 * App.css 等の CSS ファイルに hex 色・rgba/rgb 直書きがないか検査する。
 * index.css・tokens.css は変数定義ファイルのため除外対象。
 *
 * 使用方法: node scripts/check-css-hardcoded-colors.js
 * CI: npm run check:css-colors
 */

import { readFileSync, readdirSync, statSync } from 'fs';
import { join, extname, basename, relative, dirname } from 'path';
import { fileURLToPath } from 'url';

const __dirname = dirname(fileURLToPath(import.meta.url));
const SRC_DIR = join(__dirname, '../src');

// 変数定義ファイルは除外（hex / rgba が値定義として書かれる）
const EXCLUDE_FILES = new Set(['index.css', 'tokens.css']);

// hex カラーパターン
const HEX_PATTERN = /#[0-9a-fA-F]{3,8}(?![0-9a-fA-F])/;

// rgba/rgb 直書きパターン（var() や CSS変数定義行は除外）
const RGBA_PATTERN = /\brgba?\s*\(/;

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
    // CSS変数定義行（--xxx:）はスキップ（index.css は除外済みだが念のため）
    if (/^\s*--[\w-]+\s*:/.test(line)) return;

    if (HEX_PATTERN.test(trimmed)) {
      const rel = relative(process.cwd(), file);
      console.error(`❌ ${rel}:${i + 1}`);
      console.error(`   ${trimmed}`);
      console.error(
        `   → CSS変数を使ってください: var(--bg-surface) 等（ADR-067）`
      );
      hasError = true;
    } else if (RGBA_PATTERN.test(trimmed)) {
      const rel = relative(process.cwd(), file);
      console.error(`❌ ${rel}:${i + 1}`);
      console.error(`   ${trimmed}`);
      console.error(
        `   → rgba/rgb 直書き禁止。index.css にトークンを追加して var(--xxx) で参照してください（ADR-067）`
      );
      hasError = true;
    }
  });
}

if (hasError) {
  console.error('');
  console.error(
    '❌ CSS色チェック FAILED: index.css 以外のCSSファイルにhex/rgba色を直書きしないでください'
  );
  process.exit(1);
} else {
  console.log('✅ CSS色チェック PASSED（hex・rgba 違反なし）');
  process.exit(0);
}
