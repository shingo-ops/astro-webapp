# 開発ガイドライン

## ブランチ戦略

```
feature/xxx → develop → main（本番）
```

- `main` への直接 push は禁止（ブランチ保護により物理的にブロックされます）
- 必ず PR を作成し、CI が全て通過してからマージしてください
- VPS への手動デプロイ禁止（GitHub Actions 経由のみ）

## DB スキーマ変更（models.py に Column を追加する場合）

**以下の3点をセットで行わないと CI がブロックします。**

```
1. migrations/NNN_description.sql   ← ADD COLUMN IF NOT EXISTS + DEFAULT 必須
2. scripts/migrate_xxx.py           ← SQL 実行スクリプト
3. .github/workflows/deploy.yml     ← 実行ステップを追記
```

### migration SQL のテンプレート

```sql
-- migrations/NNN_add_xxx_to_yyy.sql
ALTER TABLE public.yyy
    ADD COLUMN IF NOT EXISTS xxx BOOLEAN NOT NULL DEFAULT FALSE;

CREATE INDEX IF NOT EXISTS idx_yyy_xxx ON public.yyy(xxx);
```

- `ADD COLUMN IF NOT EXISTS` — 冪等（何度実行しても安全）
- `DEFAULT` — 既存行に値が入る（これがないと NULL になり壊れる）

## PR を作成したら

PR テンプレートのチェックリストを確認してください。
特に「DB スキーマ変更時」の項目は CI でもチェックされますが、自分でも確認してください。

## CI チェック一覧

| ワークフロー | トリガー | 内容 |
|---|---|---|
| Backend Tests | 常時 | pytest 全スイート |
| Migration Guard | models.py 変更時 | deploy.yml 追記の確認 |
| Migration SQL Test | migrations/ 変更時 | 実 DB での SQL 実行テスト |
| Tenant Schema Integrity Check | backend/migrations/scripts 変更時 | テナントスキーマ整合性 |
| E2E Tests | 常時 | Playwright E2E |
