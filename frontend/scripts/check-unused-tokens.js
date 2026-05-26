#!/usr/bin/env node
/**
 * check-unused-tokens.js (ADR-073)
 *
 * tokens.css + index.css に定義された CSS カスタムプロパティのうち、
 * src/ 配下のファイルで var(--xxx) として参照されていないものを報告する。
 *
 * 注意: CI ブロックなし（終了コード 0）。定期的な監査目的。
 * 使用方法: npm run audit:unused-tokens
 */

import { readFileSync, readdirSync, statSync } from 'fs';
import { join, extname, dirname } from 'path';
import { fileURLToPath } from 'url';

const __dirname = dirname(fileURLToPath(import.meta.url));
const ROOT = join(__dirname, '..');
const SRC_DIR = join(ROOT, 'src');

// トークン定義ファイル
const TOKEN_FILES = [
  join(SRC_DIR, 'tokens.css'),
  join(SRC_DIR, 'index.css'),
];

// 検索対象ファイル拡張子
const SEARCH_EXTS = new Set(['.css', '.tsx', '.ts']);

// デザインシステム専用トークン（DesignSystemPage のデモ用）は除外
const EXEMPT_PREFIXES = ['--ds-'];

function extractTokenNames(content) {
  const names = [];
  // "--xxx-yyy:" の形式で定義された変数名を抽出
  const regex = /^\s*(--[\w-]+)\s*:/gm;
  let m;
  while ((m = regex.exec(content)) !== null) {
    names.push(m[1]);
  }
  return names;
}

function collectFiles(dir, results = []) {
  for (const entry of readdirSync(dir)) {
    const full = join(dir, entry);
    const stat = statSync(full);
    if (stat.isDirectory()) {
      collectFiles(full, results);
    } else if (SEARCH_EXTS.has(extname(entry))) {
      results.push(full);
    }
  }
  return results;
}

// 全トークン名を収集
const allTokens = new Map(); // name → source file
for (const tokenFile of TOKEN_FILES) {
  const content = readFileSync(tokenFile, 'utf8');
  for (const name of extractTokenNames(content)) {
    if (!allTokens.has(name)) {
      allTokens.set(name, tokenFile.replace(ROOT + '/', ''));
    }
  }
}

// src/ 配下の全ファイルを検索して var(--xxx) 参照を収集
const allFiles = collectFiles(SRC_DIR);
const usedTokens = new Set();

for (const file of allFiles) {
  const content = readFileSync(file, 'utf8');
  const regex = /var\((--[\w-]+)/g;
  let m;
  while ((m = regex.exec(content)) !== null) {
    usedTokens.add(m[1]);
  }
}

// 未使用トークンを報告
const unused = [];
for (const [name, source] of allTokens) {
  if (EXEMPT_PREFIXES.some((p) => name.startsWith(p))) continue;
  if (!usedTokens.has(name)) {
    unused.push({ name, source });
  }
}

if (unused.length === 0) {
  console.log('✅ audit:unused-tokens — 未使用トークンはありません');
  process.exit(0);
}

console.log(`⚠️  audit:unused-tokens — ${unused.length} 件の未使用トークンが見つかりました:\n`);
for (const { name, source } of unused) {
  console.log(`   ${name.padEnd(45)} (${source})`);
}
console.log('');
console.log('対処: 不要なトークンは削除、または使用箇所がある場合は検索パターンを確認してください。');
console.log('     意図的に未使用の場合は EXEMPT_PREFIXES に prefix を追加してください。');
// CI ブロックなし
process.exit(0);
