#!/usr/bin/env node
/**
 * check-concurrently-usage.js
 *
 * frontend/package.json の check:all スクリプトが concurrently を使用していることを確認する。
 * && による直列実行への退行を防ぐ。
 *
 * 使用方法: node scripts/check-concurrently-usage.js
 * CI: npm run check:concurrently
 */

import { readFileSync } from 'fs';
import { join } from 'path';
import { execSync } from 'child_process';

const repoRoot = execSync('git rev-parse --show-toplevel', { encoding: 'utf8' }).trim();
const pkgPath = join(repoRoot, 'frontend', 'package.json');

const pkg = JSON.parse(readFileSync(pkgPath, 'utf8'));
const checkAll = pkg.scripts?.['check:all'] ?? '';

if (!checkAll.startsWith('concurrently ')) {
  console.error('ERROR: check:all は concurrently で始まる必要があります。');
  console.error('  現在の値:', checkAll.slice(0, 80) + (checkAll.length > 80 ? '...' : ''));
  console.error('');
  console.error('  直列 (&&) への退行が検出されました。');
  console.error('  修正方法: concurrently --kill-others-on-fail --max-processes 6 "..." を使用してください。');
  process.exit(1);
}

console.log('OK: check:all は concurrently を使用しています');
