# ADR-019 Runbook — `recording/english-ui` の一時デプロイと巻き戻し

| 項目 | 値 |
|---|---|
| 起票日 | 2026-05-09 |
| 根拠 ADR | [ADR-019](../adr/ADR-019.md) |
| 担当 | しんごさん（PR マージ操作 / VPS 確認） |
| 補助 | Hikky-dev（PR 起票 / migration 冪等性検証） |
| 影響範囲 | 本番 `app.salesanchor.jp` の UI のみ。バックエンド API・DB スキーマは無変更 |

---

## 0. 背景

Meta App Review のレビュアーは録画を見るだけでなく **本番アプリを LIVE で操作** して Permission の動作を確認する。本番が日本語 UI のままだと操作できずリジェクトリスクが高いため、審査期間中のみ `recording/english-ui` ブランチを `main` にマージし本番デプロイする。審査通過後は `develop` を `main` に再マージして日本語 UI に戻す。

このランブックは [ADR-019](../adr/ADR-019.md) の「パートナーへの委任事項」3 項目に対応する。なお [docs/handoff/meta-screencast-handoff-2026-05-09.md](../handoff/meta-screencast-handoff-2026-05-09.md) §5 では「`recording/english-ui` は PR / merge / 本番反映なし」と書かれているが、ADR-019 はこれを **明示的に上書き** する（同日付で起票された後発判断）。

---

## 1. 全体フロー

```
[現状]                       [審査直前]                   [審査通過後]
                              merge                        merge
develop  ──────────────►  recording/english-ui  ──────►  develop
   │                          │  (English UI)              │  (Japanese UI 復帰)
   │  PR (base=main)          │  PR (base=main)            │  PR (base=main)
   ▼                          ▼                            ▼
 main (Japanese UI)       main (English UI)            main (Japanese UI)
                              │                            │
                              ▼ deploy.yml                  ▼ deploy.yml
                          app.salesanchor.jp           app.salesanchor.jp
```

`main` への push を契機に `.github/workflows/deploy.yml` が自動発火し、LP rsync + VPS 上の `git pull` + `docker compose up --build` + マイグレーションが走る。**追加のワークフロー改修は不要** — 既存の deploy.yml をそのまま使う。

---

## 2. デプロイ手順（`recording/english-ui` → 本番）

### 2-1. 事前確認（Hikky-dev）

| チェック項目 | 確認方法 |
|---|---|
| `recording/english-ui` が origin に push されている | `git fetch origin && git log -1 origin/recording/english-ui` |
| `recording/english-ui` のテキスト変更が UI 文言のみで機能差分がないこと | `git diff origin/main...origin/recording/english-ui -- 'frontend/src/**' \| less` |
| バックエンド・migration・deploy.yml に変更がないこと | `git diff origin/main...origin/recording/english-ui -- backend/ migrations/ scripts/migrate_*.py .github/workflows/` が空 |
| ローカル動作確認（任意） | `git checkout recording/english-ui && (cd frontend && npm run dev)` で英語 UI を目視 |

> ⚠️ もし上記 3 番目で差分が出る場合は **ADR-019 のスコープ逸脱**。しんごさんに即エスカレーションし、本ランブックでの merge は中止する。

### 2-2. ブランチを最新 `main` に追従させる（Hikky-dev、必須）

`recording/english-ui` が古い `develop` を基底にしている場合、 `deploy.yml` や `migrations/` が `main` の最新と乖離する可能性がある（特に migration043〜046 や Phase 1-D 系）。**マージ前に `recording/english-ui` を最新 `main` に rebase / merge** して、UI 以外を `main` と完全一致させる。

```
git fetch origin
git checkout recording/english-ui
git pull --rebase origin recording/english-ui

# main を取り込む（rebase でも merge でも可。コンフリクトは UI 文言のみのはず）
git merge origin/main --no-ff -m "merge main into recording/english-ui (ADR-019 pre-deploy sync)"

# UI 以外に diff が残っていないか再確認
git diff origin/main...HEAD -- backend/ migrations/ scripts/migrate_*.py .github/workflows/ docker-compose.yml

git push origin recording/english-ui
```

コンフリクトが UI 以外にも発生した場合は止めて Web Claude / しんごさん相談。

### 2-3. PR 作成（Hikky-dev）

main は Branch Protection で直 push 禁止のため必ず PR 経由（[docs/BRANCH_PROTECTION_SETUP.md](../BRANCH_PROTECTION_SETUP.md) §2）。

```
gh pr create \
  --base main \
  --head recording/english-ui \
  --title "ADR-019: Meta審査期間中の英語UI一時デプロイ" \
  --body "$(cat <<'EOF'
## ADR
[ADR-019](../docs/adr/ADR-019.md) — Meta App Review 期間中のみ英語 UI を一時デプロイ。

## 変更内容
- `frontend/` の表示文言を英語化（recording/english-ui で作業済）
- バックエンド・DB・deploy.yml は無変更

## デプロイ
このマージにより `.github/workflows/deploy.yml` が自動発火し、`app.salesanchor.jp` が英語 UI に切り替わる。

## ロールバック
Meta 審査通過後は `develop → main` PR を作成して再マージし、日本語 UI に戻す（[runbook](../docs/runbooks/adr-019-english-ui-temporary-deploy.md) §4）。
EOF
)"
```

### 2-4. PR マージ（しんごさん）

- PR の Files Changed タブで「UI 文言のみ」であることを最終確認
- `Merge pull request`（merge commit / squash どちらでも可、本リポジトリは merge 履歴重視ではないので squash 推奨）
- 直後に [GitHub Actions](https://github.com/shingo-ops/salesanchor/actions/workflows/deploy.yml) を開いて `Deploy to VPS` の実行を確認

### 2-5. 本番反映の確認

deploy.yml の Step 6（health check）が緑になったあと、ブラウザで以下を確認:

| チェック項目 | 期待値 |
|---|---|
| https://app.salesanchor.jp/ ログイン画面 | 英語表示（"Sign in" 等） |
| https://app.salesanchor.jp/ ダッシュボードのメニュー | 英語表示 |
| https://api.salesanchor.jp/api/health | `{"status":"ok"}` |
| https://salesanchor.jp/ LP | 既存表示（LP は recording/english-ui の変更対象外、影響なし） |

問題があれば即 §4 のロールバックへ。

---

## 3. デプロイ時の `deploy.yml` 影響評価（migration046 等の冪等性）

ADR-019 §パートナーへの委任事項 §3 への回答。

### 3-1. deploy.yml が走らせるマイグレーション

`recording/english-ui` を §2-2 で最新 `main` に追従させた状態で merge すれば、deploy.yml は `main` 最新と同一（recording/english-ui には deploy.yml 変更なし）になる。発火するマイグレーションは現行 main と同じ:

| ファイル | 種別 | 冪等性ガード |
|---|---|---|
| 013_add_meta_webhook_idempotency.sql | psql 直 | 確認済 |
| 014_create_current_tenant_id_function.sql | psql 直 | `CREATE OR REPLACE FUNCTION` |
| 018_extend_permissions_with_menu_grain.sql | psql 直 | `ADD COLUMN IF NOT EXISTS` + `INSERT ... ON CONFLICT DO NOTHING` |
| 023_fix_system_admin_is_system_flag.sql | psql 直 | `WHERE is_system = FALSE` で再実行 no-op |
| 024_add_staff_bots_permissions.sql | psql 直 | `INSERT ... ON CONFLICT (key) DO NOTHING` |
| 025_resync_owner_admin_all_permissions.sql | psql 直 | `ON CONFLICT DO NOTHING` |
| 026〜037（Phase 1-B 系） | psql 直 | 全て `IF NOT EXISTS` / pre-condition assertion / `IF EXISTS` |
| 038_add_products_phase1c_columns.sql | psql 直 | `ADD COLUMN IF NOT EXISTS` / `CREATE INDEX IF NOT EXISTS` |
| 039_create_data_deletion_logs.sql | psql 直 | `IF NOT EXISTS` / `OR REPLACE` |
| **046_adr015_lead_foundation.sql**（テンプレート）| Python ランナー `scripts/migrate_adr015_lead_foundation.py` | 下記参照 |

> NOTE: 015-017 / 019-022 は `{schema}` プレースホルダ含むテンプレートで、deploy.yml では自動実行しない。新テナント作成は `backend/app/services/tenant.py` のテンプレートが全テーブルを作るので、本ランブックの merge による影響はない。

### 3-2. migration046 の冪等性検証（ADR-019 で名指しされた論点）

`migrations/046_adr015_lead_foundation.sql` を全文読んだ結果、以下のガードで冪等:

| 操作 | ガード |
|---|---|
| `leads` への列追加（country, target_titles, first_inquiry_at, ai_collection_state など 19 列）| `ALTER TABLE ... ADD COLUMN IF NOT EXISTS` |
| `leads` 用インデックス 3 本（next_action_date / ai_collection_state / escalation_flag）| `CREATE INDEX IF NOT EXISTS` |
| `lead_playbook` テーブル新設 | `CREATE TABLE IF NOT EXISTS` |
| `lead_playbook` 用インデックス | `CREATE INDEX IF NOT EXISTS` |
| `lead_playbook` 用 RLS ポリシー | `DO $...$` ブロック内で `pg_policies` を `SELECT 1` チェックして条件付き `CREATE POLICY` |
| `set_updated_at_lead_playbook()` 関数 | `CREATE OR REPLACE FUNCTION` |
| `trigger_set_updated_at_lead_playbook` トリガ | `DROP TRIGGER IF EXISTS` → `CREATE TRIGGER`（毎回張り直しで実害なし） |
| `customer_contact_channels.external_id` 列追加 + インデックス | `ADD COLUMN IF NOT EXISTS` / `CREATE INDEX IF NOT EXISTS` |

ランナー `scripts/migrate_adr015_lead_foundation.py` は `pg_namespace` 走査で全 `tenant_NNN` schema に展開する非テンプレート方式（既に develop / main で本番適用済 / 2026-05-07 初版）。

**結論**: `recording/english-ui` を merge して deploy.yml が再発火しても migration046 は no-op。**追加対応不要**。

### 3-3. その他のリスク

| 項目 | 影響 | 対策 |
|---|---|---|
| `.env` 環境変数の自動補完（deploy.yml Step 2）| `META_*` / `METADATA_FERNET_KEY` 等は既に設定済のため `grep -q "^KEY=" \|\| echo` で skip される | 対応不要 |
| LP（`lp/`）の rsync `--delete` | recording/english-ui に lp 変更がない場合は main と同一 dist が再 deploy されるだけ | 対応不要 |
| Docker volume / DB 状態 | スキーマ変更なし、データ操作なし | 対応不要 |
| Frontend assets キャッシュ | CDN は不在（直接 nginx 配信）。ブラウザキャッシュのみ。Hard reload で英語化を確認 | 確認のみ |

---

## 4. ロールバック手順（審査通過後 → 日本語 UI に戻す）

ADR-019 §パートナーへの委任事項 §2 への回答。

### 4-1. 前提

- Meta App Review が **Approved** ステータスになっている、または PO が「もう英語 UI 不要」と判断した
- `develop` ブランチには `recording/english-ui` の文言変更が **入っていない** ことを再確認
  - `git log origin/develop --oneline | grep -i "english\|i18n"` で念のため見回す
  - 入っていれば、ロールバックでまた英語化されてしまうので相談

### 4-2. ロールバック PR 作成（Hikky-dev）

通常の develop → main リリース PR と同じ手順（[CLAUDE.md ブランチ運用ルール](../../CLAUDE.md) §「develop → main も PR 経由」）。

```
gh pr create \
  --base main \
  --head develop \
  --title "ADR-019 rollback: Meta審査通過、日本語UIに復帰" \
  --body "$(cat <<'EOF'
## ADR
[ADR-019](../docs/adr/ADR-019.md) ロールバックフェーズ。

Meta App Review が Approved になったため、`recording/english-ui` を取り込んだ `main` を最新 `develop`（日本語 UI ＋審査期間中の develop 進捗）で上書きする。

## 動作
- マージにより `.github/workflows/deploy.yml` が再発火
- VPS 上で `git pull origin main` → `docker compose up -d --build` → migrations 再実行（全て idempotent、§3 参照）
- `app.salesanchor.jp` の UI が日本語表示に戻る
EOF
)"
```

### 4-3. PR マージ（しんごさん）

- 通常通り PR をマージ
- deploy.yml の自動発火を確認
- ブラウザで `app.salesanchor.jp` が日本語表示に戻ったことを確認

### 4-4. 後片付け

```
# recording/english-ui ブランチを削除（ローカル）
git branch -D recording/english-ui

# origin からも削除（しんごさん or Hikky-dev）
git push origin --delete recording/english-ui
```

`recording/english-ui` は ADR-019 のライフサイクルにより、ロールバック完了後は **不要** になる。次回 Meta 再申請が必要な場合は `recording/english-ui-v2` 等で別途切り直す。

---

## 5. 想定外シナリオと対処

| シナリオ | 対処 |
|---|---|
| §2-2 の `git diff` で UI 以外の差分が出る | しんごさんに即エスカレーション、本ランブックでの merge は中止 |
| デプロイ後 health check が失敗 | `gh run view <run-id> --log` で原因確認、必要なら §4 のロールバックを前倒し実行 |
| 英語化が一部画面で漏れている | `recording/english-ui` を update して再 push → main に再 PR（このランブックを再実行） |
| migration046 が冪等性違反で失敗（理論上は無いが念のため） | deploy.yml ログを保存し、§3-2 の表を再確認の上 PO 相談。`develop` 側の migration047 として対症 PR を起こす |
| Meta 審査がリジェクトされる | ロールバック前にしんごさんと相談。再申請なら英語 UI 維持、断念なら §4 |

---

## 6. 完了条件

### デプロイ側（§2）

- [ ] `recording/english-ui` が最新 `origin/main` を取り込んでおり、UI 文言以外の差分が `0` であること
- [ ] PR `recording/english-ui → main` が作成されている
- [ ] PR のマージで deploy.yml が成功し、health check が緑
- [ ] `app.salesanchor.jp` のログイン画面・ダッシュボードが英語表示
- [ ] `api.salesanchor.jp/api/health` が 200 OK

### ロールバック側（§4）

- [ ] Meta App Review が Approved ステータス（または PO 判断で英語 UI 不要）
- [ ] PR `develop → main` が作成・マージされている
- [ ] deploy.yml が成功し health check が緑
- [ ] `app.salesanchor.jp` が日本語表示に復帰
- [ ] `recording/english-ui` ブランチが origin から削除済

### deploy.yml 影響評価（§3）

- [x] migration046 を含む全 migration の冪等性ガードを §3-1 / §3-2 で確認済
- [x] deploy.yml への変更は不要であることを確認済

---

## 参考

- [ADR-019: Meta審査期間中の英語UI一時デプロイ](../adr/ADR-019.md)
- [docs/handoff/meta-screencast-handoff-2026-05-09.md](../handoff/meta-screencast-handoff-2026-05-09.md)（§5 の運用ルールは ADR-019 で上書き）
- [docs/BRANCH_PROTECTION_SETUP.md](../BRANCH_PROTECTION_SETUP.md)
- [.github/workflows/deploy.yml](../../.github/workflows/deploy.yml)
- [migrations/046_adr015_lead_foundation.sql](../../migrations/046_adr015_lead_foundation.sql)
