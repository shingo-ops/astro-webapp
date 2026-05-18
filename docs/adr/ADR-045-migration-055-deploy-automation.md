# ADR-045: ADR-041 migration 055 の本番適用と deploy.yml 自動化

## ステータス

Accepted

## 背景

ADR-041 (Meta page connection fallback) を本番（main）にリリースしたが、
migration 055（granted_scopes 列追加）が VPS に未適用のため、
tenant_meta_config 系の全 API が HTTP 500 で失敗している。

### 具体的な事象

- `backend/app/routers/meta_inbox.py:284` (connect_callback) が
  granted_scopes 列に INSERT しようとして `UndefinedColumnError` で失敗
- `backend/app/routers/meta_inbox.py:794` (list_channels) が
  `InFailedSQLTransactionError` で連鎖失敗
- tenant_006 (review@salesanchor.jp) で `/channels` が HTTP 500
- 既存 Facebook Page 接続が UI に表示されない
- "An internal error occurred. Please contact support." エラー表示

### 直接原因

- `migrations/055_add_granted_scopes.sql` と
  `scripts/migrate_adr041_granted_scopes.py` は PR #389 (ADR-041 実装) に
  含まれていたが、`.github/workflows/deploy.yml` に
  migration 自動実行ステップが追記されていなかった
- 結果、コードは本番に反映されたが DB スキーマは更新されなかった

### 関連 referent

- `.github/workflows/deploy.yml`（修正対象、現状 migration 実行なし）
- `migrations/055_add_granted_scopes.sql`（既存、適用待ち）
- `scripts/migrate_adr041_granted_scopes.py`（既存、テナント全展開スクリプト）
- `backend/app/routers/meta_inbox.py:284`（エラー発生箇所）
- `backend/app/routers/meta_inbox.py:794`（連鎖失敗箇所）
- `tenant_006.tenant_meta_config`（granted_scopes 列が不在のテーブル）

## What

### 1. deploy.yml に migration 自動実行ステップを追加

`.github/workflows/deploy.yml` の "Deploy to VPS" ステップ内で、
`docker compose up` 完了後・"Verify deployment" の前に、以下を実行する：

```bash
docker compose exec -T backend python scripts/migrate_adr041_granted_scopes.py
```

`migrate_adr041_granted_scopes.py` は冪等性が保証されている
（`IF NOT EXISTS` + `WHERE granted_scopes IS NULL` で2回目以降は no-op）。

### 2. 本番への即時適用

本ADR実装PRが main にマージされた瞬間、deploy.yml が再発火し、
上記の migration 適用ステップで migration 055 が
tenant_006 を含む全テナントに自動適用される。

### 3. 検証強化

`.github/workflows/deploy.yml` の "Verify deployment" ステップに以下を追加：

- 全テナントスキーマで `tenant_meta_config.granted_scopes` 列の存在確認
- backfill 完了確認（NULL のレコードが残っていないこと）

失敗した場合、deploy.yml ステップを失敗扱いにする。

## Why

- 本番障害が継続中：tenant_006（撮影テナント）で `/channels` が 500
- 手動 VPS 操作は CLAUDE.md / セッション指示で禁止されており、
  自動化された deploy.yml 経由でしか migration 適用ができない
- ADR-041 のコード自体は正しい。DB スキーマだけが本番で古い状態
- 再発防止のため、今後の migration も deploy.yml で自動化される構造が必要

## 実装手順

1. `docs/adr/ADR-045-migration-055-deploy-automation.md` 追加（本ファイル）
2. `.github/workflows/deploy.yml` に migration 055 実行ステップ追加
3. `.github/workflows/deploy.yml` の Verify ステップに granted_scopes 確認追加
4. develop → main release PR 作成 → マージ → deploy.yml 自動発火

## Scope外

- ADR-041 のコード本体の変更（不要）
- migration 全体の自動化ルール改訂（別ADR でフレームワーク化検討）
- DB バックアップ取得の自動化（別ADR）
- migration 055 以外の過去 migration の遡及適用（既に適用済みのため不要）
- rollback 機構の整備（別ADR）

## 事業上の制約

- 本番障害継続中のため、本ADR は最速で実装すべき
- 撮影復帰が止まっており、復旧後に screenplay v2 で撮影継続
- migration 適用は冪等なので、2回実行されても安全

## 変更履歴

- 2026-05-18: 本番障害対応 hotfix として起案
