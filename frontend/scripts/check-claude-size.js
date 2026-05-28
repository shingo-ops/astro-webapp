#!/usr/bin/env node
/**
 * check-claude-size.js
 *
 * CLAUDE.md ファイルの行数が上限を超えていないか検査する。
 * 上限を超えた場合、「ルール追加決定木」に従って適切なファイルに移動するよう促す。
 *
 * 使用方法: node scripts/check-claude-size.js
 * CI: npm run check:claude-size
 */

import { readFileSync, existsSync } from 'fs';
import { join } from 'path';
import { execSync } from 'child_process';

const repoRoot = execSync('git rev-parse --show-toplevel', { encoding: 'utf8' }).trim();


// 各 CLAUDE.md の上限行数（超過すると CI / pre-commit がブロック）
// 新規サブディレクトリ CLAUDE.md を追加した場合はここに登録すること（ADR-076）
// 例: { path: 'backend/db/CLAUDE.md', limit: 70 },
const LIMITS = [
  { path: 'CLAUDE.md', limit: 120 },
  { path: 'frontend/CLAUDE.md', limit: 90 },
  { path: 'backend/CLAUDE.md', limit: 70 },
];

// LIMITS に未登録のサブディレクトリ CLAUDE.md を自動検出して警告（ADR-076）
const registeredPaths = new Set(LIMITS.map(l => l.path));
try {
  const found = execSync(
    'find . -name "CLAUDE.md" -not -path "./node_modules/*" -not -path "./.git/*" -not -name "./CLAUDE.md"',
    { encoding: 'utf8', cwd: repoRoot }
  ).trim().split('\n').filter(Boolean).map(p => p.replace(/^\.\//, ''));
  for (const p of found) {
    if (p !== 'CLAUDE.md' && !registeredPaths.has(p)) {
      console.warn(`⚠️  ${p}: LIMITS 未登録 — check-claude-size.js の LIMITS 配列に追加してください（ADR-076）`);
    }
  }
} catch { /* find が空結果の場合は無視 */ }

let hasError = false;

for (const { path: relPath, limit } of LIMITS) {
  const fullPath = join(repoRoot, relPath);
  if (!existsSync(fullPath)) continue;

  const content = readFileSync(fullPath, 'utf8');
  const split = content.split('\n');
  // wc -l 相当（末尾の空行は除外）
  const lines = split[split.length - 1] === '' ? split.length - 1 : split.length;
  if (lines > limit) {
    console.error(`❌ ${relPath}: ${lines}行（上限${limit}行）`);
    console.error(`   → 詳細ルールをサブディレクトリ CLAUDE.md に分割してください（ADR-076）`);
    console.error(`   　 例: backend/db/CLAUDE.md、backend/tenant/CLAUDE.md`);
    console.error(`   　 ファイル名は必ず CLAUDE.md にすること（それ以外は AI が自動ロードしない）`);
    console.error(`   　 追加後は LIMITS 配列に登録して CI 監視対象に加えること`);
    hasError = true;
  }
}

if (hasError) {
  console.error('');
  console.error('❌ CLAUDE.md サイズチェック FAILED: 上限行数を超えています');
  process.exit(1);
} else {
  console.log('✅ CLAUDE.md サイズチェック PASSED');
  process.exit(0);
}
