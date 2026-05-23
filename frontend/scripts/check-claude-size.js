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

// サブディレクトリの CLAUDE.md のみ対象（ルート CLAUDE.md は既存の大規模ファイルのため除外）
const LIMITS = [
  { path: 'frontend/CLAUDE.md', limit: 60 },
  { path: 'backend/CLAUDE.md', limit: 45 },
];

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
    console.error(`   → 新しいルールは末尾の「ルール追加決定木」に従い適切なファイルに書いてください`);
    console.error(`   　 CI/ESLint強制済み → 書かない`);
    console.error(`   　 frontend/のみ → frontend/CLAUDE.md`);
    console.error(`   　 backend/のみ  → backend/CLAUDE.md`);
    console.error(`   　 agentの手順   → ~/.claude/agents/`);
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
