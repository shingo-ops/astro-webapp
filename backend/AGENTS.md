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

## Migration 適用経路

新規 migration を追加した場合:
- 既存全テナント + 新規作成テナント両方への適用経路を PR body に明記する
- PostgreSQL 実機で `information_schema.columns` により全テナント schema 整合を確認（SQLite 不可）

---

## 品質チェック

```bash
make lint    # ruff / bandit / mypy
make check   # lint + pytest（初回: pip install -r requirements-dev.txt）
```
