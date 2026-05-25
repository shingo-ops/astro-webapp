#!/usr/bin/env node
/**
 * check-css-fixed-position.js
 *
 * src/pages/ 以下の CSS ファイルに position: fixed が書かれていないか検査する。
 *
 * 背景: アバターボタン (.avatar-btn) は topbar.css で
 *   position: fixed; top: var(--avatar-zone-top); right: var(--avatar-zone-right);
 * に固定されている。pages/ 配下の CSS で同座標に fixed 要素を置くと
 * アバターの下に隠れるバグが発生する（InboxPage.css .inbox-header-btns で発生済み）。
 *
 * 正しい実装: <PageLayout headerAction={...}> を使う
 *   → .page-layout-header は padding-right: var(--page-header-avatar-clearance) (68px) を確保済み
 *
 * 例外: 同行に "fixed-ok:" コメントを含む行はスキップ（モーダルオーバーレイ等）
 *   例: position: fixed; inset: 0; /* fixed-ok: modal-overlay * /
 *
 * 使用方法: node scripts/check-css-fixed-position.js
 * CI: npm run check:css-fixed-position（check:all に含まれる）
 */

import { readFileSync, readdirSync, statSync } from 'fs';
import { join, extname, relative, dirname } from 'path';
import { fileURLToPath } from 'url';

const __dirname = dirname(fileURLToPath(import.meta.url));
const PAGES_DIR = join(__dirname, '../src/pages');

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

const cssFiles = collectCssFiles(PAGES_DIR);
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

    // position: fixed が含まれる行を検出
    if (!/position\s*:\s*fixed/.test(trimmed)) return;

    // 例外コメント "fixed-ok:" が同行にあればスキップ
    if (line.includes('fixed-ok:')) return;

    const rel = relative(process.cwd(), file);
    console.error(`❌ ${rel}:${i + 1}`);
    console.error(`   ${trimmed}`);
    console.error(
      `   → pages/ の CSS に position: fixed を書かないでください。`
    );
    console.error(
      `     代わりに <PageLayout headerAction={...}> を使ってください（frontend/CLAUDE.md 参照）。`
    );
    console.error(
      `     例外（モーダル等）は同行に /* fixed-ok: 理由 */ コメントを付与してください。`
    );
    hasError = true;
  });
}

if (hasError) {
  console.error('');
  console.error(
    '❌ CSS position:fixed チェック FAILED: pages/ 配下のCSSに position:fixed を書かないでください'
  );
  process.exit(1);
} else {
  console.log('✅ CSS position:fixed チェック PASSED');
  process.exit(0);
}
