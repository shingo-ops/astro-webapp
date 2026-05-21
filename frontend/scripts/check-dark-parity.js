#!/usr/bin/env node
/**
 * check-dark-parity.js (ADR-067)
 *
 * index.css の :root と :root.force-dark の CSS変数が完全に一致するか検査する。
 * ライトにあってダークにない変数（ダークモード切り替え漏れ）を検出する。
 *
 * 除外リスト: 寸法値変数（--sidebar-width-* 等）はダーク定義不要なため除外。
 *
 * 使用方法: node scripts/check-dark-parity.js
 * CI: npm run check:dark-parity
 */

import { readFileSync } from 'fs';
import { join, dirname } from 'path';
import { fileURLToPath } from 'url';

const __dirname = dirname(fileURLToPath(import.meta.url));
const CSS_PATH = join(__dirname, '../src/index.css');

// ダーク定義が不要な変数プレフィックス（寸法・レイアウト値）
const DIMENSION_PREFIXES = ['--sidebar-width-'];

const css = readFileSync(CSS_PATH, 'utf8');

function extractVarsFromBlock(blockContent) {
  const matches = blockContent.match(/^\s*(--[\w-]+)\s*:/gm) || [];
  return matches.map((m) => m.trim().replace(/:$/, ''));
}

// :root { } と :root.force-dark { } ブロックを抽出
const rootMatch = css.match(/:root\s*\{([\s\S]*?)\n\}/);
const darkMatch = css.match(/:root\.force-dark\s*\{([\s\S]*?)\n\}/);

if (!rootMatch || !darkMatch) {
  console.error('❌ :root または :root.force-dark ブロックが見つかりません');
  process.exit(1);
}

const lightVars = extractVarsFromBlock(rootMatch[1]);
const darkVars = new Set(extractVarsFromBlock(darkMatch[1]));

const missingInDark = lightVars.filter((v) => {
  if (DIMENSION_PREFIXES.some((prefix) => v.startsWith(prefix))) return false;
  return !darkVars.has(v);
});

const extraInDark = [...darkVars].filter((v) => !lightVars.includes(v));

let hasError = false;

if (missingInDark.length > 0) {
  console.error('');
  console.error('❌ ダークモード変数パリティチェック FAILED');
  console.error('');
  console.error(':root に定義があって :root.force-dark に定義がない変数:');
  missingInDark.forEach((v) =>
    console.error(`  ${v}  ← index.css の :root.force-dark に追加してください`)
  );
  console.error('');
  hasError = true;
}

if (extraInDark.length > 0) {
  console.warn('⚠️  :root.force-dark にあって :root にない変数（確認推奨）:');
  extraInDark.forEach((v) => console.warn(`  ${v}`));
}

if (hasError) {
  process.exit(1);
} else {
  console.log(
    `✅ ダークモード変数パリティチェック PASSED (${lightVars.length} 変数すべて対応済み)`
  );
  process.exit(0);
}
