# ADR-044: develop ブランチ CI 健全性の回復

## ステータス
Proposed

## 背景

2026-05-14T17:13Z のコミット `dac01e3`（HUMAN_AGENT auto-apply + Messaging window UI 削除）
以降、develop ブランチで 3 つの CI が継続的に失敗している：

1. **Backend Tests**: messaging_type 関連の 3 テストが古い仕様のまま
2. **Tenant Schema Integrity Check**: PYTHONPATH 不足で setup_tenant.py が import 失敗
3. **Frontend E2E (Playwright)**: 全 26 件失敗、起点不明（追加調査必要）

ADR-041 (PR #389) の CI 失敗もこれらの既存失敗に該当しており、本ADR完了後に
PR #389 を再CIにかけて全PASSさせる必要がある。

### 関連 referent（事前調査結果）
- 失敗起点コミット: `dac01e3` (2026-05-14T17:13Z)
- 関連ファイル: `backend/tests/test_message_send.py:434,658`,
  `backend/tests/test_messaging_window.py:160`,
  `scripts/setup_tenant.py:45-47`,
  `.github/workflows/schema-check.yml`,
  `frontend/playwright.config.ts`, `tests-e2e/utils/auth.ts`

## What

### 1. Tenant Schema Integrity Check の修復
`.github/workflows/schema-check.yml` の "Create test tenants" ステップに以下を追加：
```yaml
env:
  PYTHONPATH: ${{ github.workspace }}/backend
```

### 2. Backend Tests の修復
以下の 3 テストを現行実装（HUMAN_AGENT auto-apply 仕様）に合わせて更新：
- `test_message_send.py:434, 658`: `"RESPONSE"` → `"MESSAGE_TAG"`
- `test_messaging_window.py:160`: `("RESPONSE", None)` → `("MESSAGE_TAG", "HUMAN_AGENT")`

各修正にコメントで「HUMAN_AGENT auto-apply 仕様 (dac01e3) に追随」と明記。

### 3. Frontend E2E (Playwright) の修復

3a. **追加調査の実施**:
- E2E run の Vite dev server 起動ログを確認
- `tests-e2e/utils/auth.ts` の IndexedDB mock 動作を確認
- `scene1-dashboard.spec.ts` の期待セレクタが現在の UI に存在するか確認

3b. **調査結果に基づき修復**:
- 環境問題 → CI 設定修正
- mock 設定問題 → `auth.ts` 修正
- セレクタ不整合 → spec ファイル or UI コード修正

3c. **検証**: 全 26 失敗が PASS することを CI で確認

### 4. PR #389 への影響確認
本ADR実装後、develop ブランチに対して CI を発火させ、
3 チェック全 PASS を確認する。

## Why
- develop ブランチが 2026-05-14 から 3 日間壊れた状態が続いている
- ADR-041 (PR #389) のマージを「既存失敗を理由に」拒否すべきか判断不能になっている
- ローンチ前に CI 健全性を回復し、今後の実装 PR の CI 結果を信頼できる状態にする
- ADR-040 で発見されたガードレール欠如の典型症状を解消する

## Scope外
- HUMAN_AGENT auto-apply 機能の ADR トレーサビリティ確認（ADR-035 名称不一致問題は別途）
- ADR-041 (PR #389) 自体の変更
- CI ガードレールの構造的強化（ADR-042 で別途対応）
- dac01e3 を起点とする他の潜在的影響範囲の網羅調査

## 事業上の制約
- 撮影復帰のため、本ADR は速やかに実装する
- Frontend E2E の追加調査は本ADR 内で完結させる（別ADR に分割しない）
- 全 3 チェックが PASS してから PR #389 のマージ判断を行う
