# backend/CLAUDE.md

`backend/` 配下の作業時のみ適用。プロジェクト全体ルールは `/CLAUDE.md` を参照。
<!-- ADR-067 Phase 5B: 2026-05-26 デザイントークン width/height 強制完了 -->

---

## マルチテナント運用

- 本番テナント: `tenant_code=highlife-jpn`（schema: `tenant_004`）
- 撮影 / Meta App Review 用: `tenant_review`（schema: `tenant_006`、Demo データのみ）
- 既定値 `test-corp` は空テナント。移行 / バッチ実行時は必ず明示:

```bash
gh workflow run run-*-migration.yml -f tenant_code=highlife-jpn
docker exec -e TENANT_CODE=highlife-jpn ...
```

---

## 新規テナント作成時の不変条件チェック（ADR-034 マージまで暫定）

詳細: `docs/adr/ADR-034-tenant-migration-automation.md`

**ADR-034 マージ前は新規テナントを作る作業すべてで以下 4 ステップを必須**:

1. 実機Messenger + Instagram DM送受信（モック/SQLite不可）
2. `SELECT * FROM public.meta_page_routing WHERE tenant_id = :new_tenant_id` で行存在確認
3. `SELECT column_name FROM information_schema.columns WHERE table_schema='tenant_NNN' AND table_name='meta_messages'` で全カラム + `message_id=text` 確認
4. 不足あれば手動ALTER/INSERTで補完

未実施 = FAIL。Coverage notes に書いて逃げない。
<!-- [SELF-DESTRUCT-ADR-034] ADR-034マージ時にこのセクションを削除すること -->

---

## Migration は additive-only（追加専用）

**カラム削除・テーブル削除・型変更を含む migration は原則禁止。**
理由: `downgrade` 関数が未整備のため、本番適用後に問題が起きても自動ロールバック不能（ADR-045:90 参照）。

- ✅ 許可: カラム追加、インデックス追加、テーブル追加、制約追加
- ❌ 要PO確認: カラム削除・リネーム、テーブル削除、型変更、データ移行を伴う変更

destructive な変更が必要な場合は必ずしんごさん（PO）に確認してから ADR を起案すること。

## Migration 適用経路

新規 migration を追加した場合:
- **additive-only 原則**: カラム削除・テーブル削除・型変更は禁止（downgrade未整備、ADR-045:90）。destructive変更はPO確認＆ADR起案必須
- **ファイル命名規則（101番以降）**: `migrations/YYYYMMDD_HHMMSS_description.sql`（例: `20260601_082000_add_foo.sql`）。連番（`NNN_`）は廃止（001〜100は既存ファイル）。タイムスタンプにより並行エージェント間の番号衝突を防ぐ。CI が形式を強制するため、連番形式は CI でブロックされる
- **`deploy.yml` 登録必須**: migration ファイルを作成したら、必ず `.github/workflows/deploy.yml` の「新しいマイグレーションはここに追加」コメント直前に psql 実行ステップを追記すること。**登録しないと本番 DB に適用されず、API が 500 エラーになる**（ADR-045, PR #1277 の前例あり）
- **CI が自動検知**: `migration-guard.yml` が新規 migration ファイルを検出し、deploy.yml に対応行がない場合 or ファイル名形式が不正な場合は PR をブロックする
- テンプレート形式（`{schema}` プレースホルダ含む）の SQL は `deploy.yml` で直接実行不可。`DO $$ ... pg_namespace` 走査形式に書き換えること
- 既存全テナント + 新規作成テナント両方への適用経路を PR body に明記する
- PostgreSQL実機で `information_schema.columns` により全テナントschema整合を確認（SQLite不可）

## 取引先 SSOT: companies（ADR-089 完了）

`customers` テーブルは廃止済み（2026-06-01 Sprint 7 DROP）。取引先は `companies` / `company_addresses` / `company_discord` を使うこと。本番DROP手順: `scripts/migrate_089_drop_customers_tables.py`（PO確認必須）。詳細: `docs/adr/ADR-089-deprecate-customers-unify-to-companies.md`

---

## Meta App Review テナント（tenant_006）パスワード管理

`scripts/setup_review_tenant.py` 実行後は必ずホスト側に保存すること（コンテナ `/tmp` は再起動で消える）。
手順詳細: `backend/scripts/CLAUDE.md`
## 品質チェック
ローカル: `make lint`（ruff/bandit/mypy）/ `make check`（lint + pytest）初回: `pip install -r requirements-dev.txt`
**ADR-072**: write endpoint は `db.commit()` 直後に `await reset_tenant_context(db, tenant_id)` 必須（`from app.database import reset_tenant_context`）。pre-commit + CI が自動 FAIL させる。
