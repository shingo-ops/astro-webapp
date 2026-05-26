#!/usr/bin/env node
/**
 * check-onboarding-doc.js
 *
 * docs/onboarding/design-system.md が存在するか確認する。
 * このファイルは新規開発者向けデザインシステム入門ドキュメント（ADR-073 軸5）。
 * 誤って削除された場合に CI がブロックして気づけるようにする。
 *
 * 使用方法: node scripts/check-onboarding-doc.js
 * CI: npm run check:onboarding-doc
 */

import { existsSync } from 'fs';
import { join, dirname } from 'path';
import { fileURLToPath } from 'url';
import { execSync } from 'child_process';

const repoRoot = execSync('git rev-parse --show-toplevel', { encoding: 'utf8' }).trim();
const docPath = join(repoRoot, 'docs/onboarding/design-system.md');

if (existsSync(docPath)) {
  console.log('[onboarding-doc] ✅ docs/onboarding/design-system.md が存在します');
  process.exit(0);
} else {
  console.error('[onboarding-doc] ❌ docs/onboarding/design-system.md が見つかりません');
  console.error('');
  console.error('  このファイルは新規開発者向けのデザインシステム入門ドキュメントです。');
  console.error('  git 履歴から復元してください:');
  console.error('    git checkout HEAD -- docs/onboarding/design-system.md');
  console.error('');
  process.exit(1);
}
