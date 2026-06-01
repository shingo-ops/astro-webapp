# backend/AGENTS.md

`backend/` 配下の作業時のみ適用。プロジェクト全体ルールは `/AGENTS.md` を参照。

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

**ADR-034 マージ前は新規テナント作成すべてで以下 4 ステップを必須**:

1. 実機 Messenger + Instagram DM 送受信（モック / SQLite 不可）
2. `SELECT * FROM public.meta_page_routing WHERE tenant_id = :new_tenant_id` で行存在確認
3. `SELECT column_name FROM information_schema.columns WHERE table_schema='tenant_NNN' AND table_name='meta_messages'` で全カラム + `message_id=text` 確認
4. 不足あれば手動 ALTER/INSERT で補完

未実施 = FAIL。Coverage notes に書いて逃げない。

---

## Migration は additive-only（追加専用）

カラム削除・テーブル削除・型変更を含む migration は禁止。
理由: downgrade 未整備のため本番適用後に自動ロールバック不能（ADR-045）。

- ✅ 許可: カラム追加・インデックス追加・テーブル追加
- ❌ 要PO確認: カラム削除・リネーム・テーブル削除・型変更

---

## Migration 適用経路

新規 migration を追加した場合:
- 既存全テナント + 新規作成テナント両方への適用経路を PR body に明記する
- PostgreSQL 実機で `information_schema.columns` により全テナント schema 整合を確認（SQLite 不可）

---

## Migration SQL の書き方（必須パターン）

**`{schema}` プレースホルダは絶対使用禁止。** psql に渡すと構文エラーになり本番デプロイが停止する（前例: PR #1345 で約1.5h停止）。

全テナントへのカラム追加・テーブル追加は必ず `DO $$ pg_namespace` 走査形式で書くこと:

```sql
DO $$
DECLARE
    schema_record RECORD;
BEGIN
    FOR schema_record IN
        SELECT nspname AS schema_name
        FROM pg_namespace
        WHERE nspname LIKE 'tenant_%'
        ORDER BY nspname
    LOOP
        RAISE NOTICE 'Processing schema: %', schema_record.schema_name;

        EXECUTE format(
            'ALTER TABLE %I.your_table
             ADD COLUMN IF NOT EXISTS new_col TEXT',
            schema_record.schema_name
        );
    END LOOP;
END
$$;
```

参考ファイル: `migrations/090_add_lead_contact_links.sql`

---

## 品質チェック

```bash
make lint    # ruff / bandit / mypy
make check   # lint + pytest（初回: pip install -r requirements-dev.txt）
```
