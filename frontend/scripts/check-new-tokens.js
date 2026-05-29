#!/usr/bin/env node
/**
 * check-new-tokens.js
 *
 * PR で tokens.css / index.css に新規トークンが追加されていないかチェックする。
 * 新規トークンが検出された場合、PR 説明の「デザイントークン変更時」チェックリストが
 * 全て ✅ になっているかを確認する。未チェックのまま CI を通過させない。
 *
 * 動作条件（全て必要）:
 *   - GITHUB_BASE_REF が設定されている（CI / pull_request イベント）
 *   - 新規トークン追加が git diff で検出された
 *
 * ローカル実行時: 常にスキップ（exit 0）
 */

import { execSync } from 'child_process';

const BASE_REF = process.env.GITHUB_BASE_REF;
const HEAD_REF = process.env.GITHUB_HEAD_REF;
const PR_BODY = process.env.PR_BODY ?? '';

if (!BASE_REF) {
  process.exit(0);
}

// develop → main の release PR のみスキップする (base=main かつ head=develop で厳密判定)。
// 新規トークンは feature → develop PR の時点で本チェック済みであり、release PR は
// Bot 自動生成で本文（チェックリスト）を編集できず、同じトークンを二重にゲートしても
// 新たな確認価値がないため。
// 注意: base=main だけで判定すると hotfix/* → main や feature/* → main（develop の
// feature ゲートを経由しない経路）まで除外され、ゲートが効かなくなる。release PR の
// head は必ず develop なので head=develop も条件に含めて厳密化する。
if (BASE_REF === 'main' && HEAD_REF === 'develop') {
  console.log(
    'ℹ️ release PR (develop → main) のため新規トークンチェックをスキップ（feature→develop PR で確認済み）。',
  );
  process.exit(0);
}

const TOKEN_FILES = ['src/tokens.css', 'src/index.css'];

let addedTokens = [];

for (const file of TOKEN_FILES) {
  let diff;
  try {
    diff = execSync(`git diff origin/${BASE_REF}...HEAD -- ${file}`, {
      encoding: 'utf8',
      stdio: ['pipe', 'pipe', 'pipe'],
    });
  } catch {
    continue;
  }

  for (const line of diff.split('\n')) {
    if (/^\+\s*(--[\w-]+)\s*:/.test(line) && !line.startsWith('+++')) {
      const match = line.match(/^\+\s*(--[\w-]+)\s*:/);
      if (match) {
        addedTokens.push({ token: match[1], file });
      }
    }
  }
}

// 新規トークンなし → 問題なし
if (addedTokens.length === 0) {
  process.exit(0);
}

console.log('');
console.log(`🆕 新規デザイントークンが ${addedTokens.length} 件検出されました:`);
for (const { token, file } of addedTokens) {
  console.log(`   ${token.padEnd(50)} (${file})`);
}
console.log('');

// PR 説明のチェックリスト検証
// チェック済み: "- [x]" or "- [X]"
const REQUIRED_ITEMS = [
  '新しいトークンを追加した場合、その',  // 理由を概要欄に記載
  '色トークンは',                         // ライト/ダーク両方
  'check:dark-parity',                    // パリティ確認
  '既存トークンで代替できないか確認',     // 重複防止
];

const checkedPattern = /^- \[x\]/im;
const hasCheckedItems = REQUIRED_ITEMS.some((item) => {
  // PR 本文から該当チェックボックス行を探す
  const lines = PR_BODY.split('\n');
  return lines.some(
    (line) => line.match(/^- \[x\]/i) && line.includes(item)
  );
});

const hasAnyTokenChecklist = PR_BODY.includes('デザイントークン変更時') ||
  PR_BODY.includes('check:dark-parity');

if (!hasAnyTokenChecklist) {
  console.error('❌ PR 説明にデザイントークンのチェックリストが記入されていません。');
  console.error('');
  console.error('📋 PR 説明の「デザイントークン変更時」セクションを全てチェックしてください:');
  console.error('   - [x] 新しいトークンを追加した場合、その理由を概要欄に記載した');
  console.error('   - [x] 色トークンは :root と :root.force-dark 両方に追加した');
  console.error('   - [x] npm run check:dark-parity でパリティ確認済み');
  console.error('   - [x] 既存トークンで代替できないか確認した');
  console.error('');
  console.error('チェック後、PR 説明を保存して CI を再実行してください。');
  process.exit(1);
}

// チェックリストがある場合、全て [x] になっているか確認
const unChecked = REQUIRED_ITEMS.filter((item) => {
  const lines = PR_BODY.split('\n');
  const found = lines.find((line) => line.includes(item));
  if (!found) return false; // 項目自体がなければ別のフォーマットと判断しスキップ
  return !found.match(/^- \[x\]/i);
});

if (unChecked.length > 0) {
  console.error('❌ デザイントークンチェックリストに未チェック項目があります。');
  console.error('   PR 説明の以下の項目を [ ] → [x] に変更してください:');
  for (const item of unChecked) {
    console.error(`   • ${item}...`);
  }
  console.error('');
  process.exit(1);
}

console.log('✅ デザイントークンチェックリスト確認済み。新規トークン追加が承認されました。');
process.exit(0);
