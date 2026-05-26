#!/bin/bash
# check-active-work-format.sh — active-work.md テーブルフォーマット検証
#
# 目的: active-work.md の列数不一致を早期検出する
#       PR#列追加(6列化)後に旧形式(5列)のエントリが混入していないかチェックする
#
# 呼び出し元:
#   - .github/workflows/active-work-lint.yml (CI)
#   - frontend/.husky/pre-push (ローカル) — active-work.md が変更された場合
#   - 手動: bash scripts/check-active-work-format.sh
#
# 終了コード:
#   0: 正常
#   1: フォーマットエラーあり

set -e

GIT_COMMON_DIR="$(git rev-parse --git-common-dir 2>/dev/null)"
if [[ "${GIT_COMMON_DIR}" = /* ]]; then
  MAIN_REPO_ROOT="$(dirname "${GIT_COMMON_DIR}")"
else
  MAIN_REPO_ROOT="$(git rev-parse --show-toplevel 2>/dev/null)"
fi

ACTIVE_WORK_FILE="${MAIN_REPO_ROOT}/.claude-pipeline/active-work.md"
EXPECTED_COLS=6
ERRORS=0

if [ ! -f "${ACTIVE_WORK_FILE}" ]; then
  echo "⚠️  active-work.md が見つかりません: ${ACTIVE_WORK_FILE}"
  exit 0
fi

echo "🔍 active-work.md フォーマット検証: ${ACTIVE_WORK_FILE}"

# テーブル行のみ抽出してチェック（ヘッダー・セパレータ・コードブロック内を除く）
# 条件: | で始まる行 AND ---|--- のセパレータ行でない AND コードブロック内でない
IN_CODE=0
LINE_NUM=0
while IFS= read -r line; do
  LINE_NUM=$((LINE_NUM + 1))
  # コードブロックの開閉を追跡
  if [[ "$line" =~ ^\`\`\` ]]; then
    IN_CODE=$(( 1 - IN_CODE ))
    continue
  fi
  [ "$IN_CODE" -eq 1 ] && continue

  # テーブル行のみ対象（| で始まる行）
  [[ "$line" =~ ^\| ]] || continue

  # セパレータ行（|---|---| 形式）はスキップ（bash 3.2 互換: grep -E で代替）
  echo "$line" | grep -qE '^\|[-| ]+\|' && continue

  # 列数をカウント（| で分割してフィールド数を数える）
  # 例: "| a | b | c |" → awk で 3フィールドと判定
  COL_COUNT=$(echo "$line" | awk -F'|' '{print NF - 2}')

  if [ "$COL_COUNT" -ne "$EXPECTED_COLS" ]; then
    echo "❌ 行 ${LINE_NUM}: ${EXPECTED_COLS}列が必要ですが${COL_COUNT}列です"
    echo "   内容: ${line}"
    ERRORS=$((ERRORS + 1))
  fi
done < "${ACTIVE_WORK_FILE}"

if [ "$ERRORS" -gt 0 ]; then
  echo ""
  echo "🚫 フォーマットエラー: ${ERRORS}件"
  echo ""
  echo "   active-work.md は現在 ${EXPECTED_COLS}列形式が必須です:"
  echo "   | ブランチ名 | 担当機能エリア | 開始日時 | 状態 | PR# | 備考 |"
  echo ""
  echo "   修正方法: 各行に PR# 列(空欄可)を追加してください"
  echo "   例: | branch | area | 2026-01-01 | IN_PROGRESS | | |"
  echo ""
  exit 1
fi

echo "✅ フォーマット正常: 全行 ${EXPECTED_COLS}列"
exit 0
