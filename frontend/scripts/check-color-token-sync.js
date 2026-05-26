#!/usr/bin/env node
/**
 * check-color-token-sync.js
 *
 * src/index.css の :root ブロックで定義されたカラートークンが
 * DesignSystemPage.tsx の COLOR_TOKENS 配列に全て含まれているか検査する。
 *
 * 対象トークンプレフィックス（名前の先頭が以下のいずれか）:
 *   bg, text, accent, border, success, warning, danger, info
 *
 * 欠落があれば exit 1 でブロック。
 *
 * 使用方法: node scripts/check-color-token-sync.js
 * CI: npm run check:color-token-sync
 */

import { readFileSync } from 'fs';
import { join, dirname } from 'path';
import { fileURLToPath } from 'url';

const __dirname = dirname(fileURLToPath(import.meta.url));
const root = join(__dirname, '..');

const CSS_PATH = join(root, 'src/index.css');
const TSX_PATH = join(root, 'src/pages/design-system/DesignSystemPage.tsx');

// --- Step 1: :root ブロックからカラートークンを抽出 ---
const cssText = readFileSync(CSS_PATH, 'utf8');

// :root { ... } のみ（:root.force-dark は除外）
const rootBlockMatch = cssText.match(/:root\s*\{([\s\S]*?)\n\}/);
if (!rootBlockMatch) {
  console.error('[color-token-sync] ❌ :root ブロックが src/index.css に見つかりません');
  process.exit(1);
}

const rootBlock = rootBlockMatch[1];
const allRootVars = [];
for (const [, name] of rootBlock.matchAll(/^\s*(--[\w-]+)\s*:/gm)) {
  allRootVars.push(name);
}

// カラートークンのプレフィックスに一致するものだけ抽出
// (?:-|$) で "--accent" 単体と "--accent-hover" 両方にマッチ
const COLOR_PREFIX_RE = /^--(bg|text|accent|border|success|warning|danger|info)(?:-|$)/;
const cssColorTokens = allRootVars.filter((v) => COLOR_PREFIX_RE.test(v));

// --- Step 2: DesignSystemPage.tsx の COLOR_TOKENS 配列から名前を抽出 ---
const tsxText = readFileSync(TSX_PATH, 'utf8');
const tsxTokens = new Set();
for (const [, name] of tsxText.matchAll(/name:\s*"(--[\w-]+)"/g)) {
  tsxTokens.add(name);
}

// --- Step 3: index.css にあって COLOR_TOKENS にないものを報告 ---
const missing = cssColorTokens.filter((v) => !tsxTokens.has(v));

if (missing.length === 0) {
  console.log(
    `[color-token-sync] ✅ 全 ${cssColorTokens.length} カラートークンが同期済み（index.css ↔ DesignSystemPage COLOR_TOKENS）`
  );
  process.exit(0);
} else {
  console.error('[color-token-sync] ❌ カラートークン同期チェック FAILED');
  console.error('');
  console.error('src/index.css :root に定義されているが COLOR_TOKENS に含まれていないトークン:');
  console.error('');
  for (const v of missing) {
    console.error(`  ${v}  ← DesignSystemPage.tsx の COLOR_TOKENS に追加してください`);
  }
  console.error('');
  console.error(`[color-token-sync] ${missing.length} トークンが未同期。COLOR_TOKENS を更新してください。`);
  process.exit(1);
}
