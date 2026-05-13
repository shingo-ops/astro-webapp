# Operations: `meta_messages.message_id` の TEXT 化（ADR-026 / Migration 052）

- **対応 ADR**: [ADR-026](../adr/ADR-026_meta_messages_message_id_text.md)
- **対応 Migration**: `migrations/052_alter_meta_messages_message_id_to_text.sql`
- **対応スクリプト**: `scripts/migrate_meta_messages_message_id_to_text.py`
- **対象**: 全 active テナント schema (`tenant_NNN`) の
  `meta_messages.message_id` カラム
- **作業者**: VPS オペレータ (Hitoshi)
- **想定所要時間**: 10 分 / テナント（オンライン ALTER のためロックは秒オーダー）

---

## なぜ必要か

Instagram の Message ID (mid) は base64 多重エンコードで 150〜200 文字を
超える。既存定義 `VARCHAR(100)` では PostgreSQL 側で

```text
asyncpg.exceptions.StringDataRightTruncationError:
value too long for type character varying(100)
```

を発生させ、IG webhook が **全件 INSERT 失敗** していた（2026-05-13 切り分け
済）。Messenger 側（mid 10〜30 文字）には影響しない。

本 migration は `meta_messages.message_id` を `VARCHAR(100)` → `TEXT` に
拡張する。`TEXT` 採用の判断は ADR-026 Q-026.1 / Hitoshi 即決：将来の Meta API
バージョンアップで mid 長が更に拡張される場合の耐性確保。

---

## 適用前チェック（必須）

### 1. ローカル / VPS から DATABASE_URL 経由で対象テナントを確認

```bash
# VPS 側
ssh ubuntu@49.212.137.46
cd /opt/salesanchor

# 全 active テナントを列挙
docker compose exec db psql -U salesanchor -d salesanchor -c \
  "SELECT id, tenant_code FROM public.tenants WHERE is_active = true ORDER BY id;"
```

### 2. 各テナント schema の現在の `message_id` カラム型を確認

```sql
-- 例: tenant_004
SELECT data_type, character_maximum_length
  FROM information_schema.columns
 WHERE table_schema = 'tenant_004'
   AND table_name = 'meta_messages'
   AND column_name = 'message_id';
-- 期待値（適用前）: data_type='character varying', character_maximum_length=100
-- 期待値（適用後）: data_type='text',              character_maximum_length=NULL
```

### 3. 既存行の最大長を確認（rollback 可能性の事前把握）

```sql
SELECT
  COALESCE(MAX(length(message_id)), 0) AS max_len,
  COUNT(*)                              AS total_rows
FROM tenant_004.meta_messages;
```

- `max_len <= 100` であれば rollback 可能性あり
- `max_len > 100` の行が混入したら down migration は失敗する（Q-026.2 判断）

---

## 適用手順

### Step 1: dry-run で適用対象を確認

```bash
# VPS 側 backend コンテナ内で実行
docker compose exec backend python /app/scripts/migrate_meta_messages_message_id_to_text.py --dry-run
```

期待出力（抜粋）:

```text
[INFO] === ADR-026 / Migration 052 (DRY-RUN) 開始 ===
[INFO] 対象テナント: N
[INFO] [dry-run] tenant_001 (tenant_code=...): 適用予定 (data_type=character varying → text)
[INFO] [dry-run] tenant_004 (tenant_code=highlife-jpn): 適用予定 (data_type=character varying → text)
[INFO] === ADR-026 / Migration 052 (DRY-RUN) 完了 ===
```

`data_type=text` がすでに表示されているテナントは skip 対象（冪等性）。

### Step 2: 本適用

```bash
docker compose exec backend python /app/scripts/migrate_meta_messages_message_id_to_text.py
```

期待出力（抜粋）:

```text
[INFO] === ADR-026 / Migration 052 (APPLY) 開始 ===
[INFO] → tenant_004 (tenant_code=highlife-jpn): ALTER (data_type=character varying → text)
[INFO] ✓ tenant_004 (tenant_code=highlife-jpn) message_id TEXT 化完了
[INFO] === ADR-026 / Migration 052 (APPLY) 完了 (exit=0) ===
```

エラー時の挙動:

- 任意のテナントで失敗 → `engine.begin()` のトランザクションが rollback
  され、当該テナントは変更されないまま例外で停止
- 既に TEXT 化されていれば自動 skip（冪等）
- 想定外の型（例: `character varying(50)` 等）に当たった場合は SQL 内の
  `RAISE EXCEPTION` で失敗 → 状況を確認の上、別途手動対応

### Step 3: 適用後確認

```bash
# psql ベースの確認
docker compose exec db psql -U salesanchor -d salesanchor -c \
  "\\d+ tenant_004.meta_messages" | grep message_id
# 期待: message_id ... text ...

# information_schema ベースの確認
docker compose exec db psql -U salesanchor -d salesanchor -c \
  "SELECT table_schema, data_type
     FROM information_schema.columns
    WHERE table_name='meta_messages' AND column_name='message_id'
    ORDER BY table_schema;"
# 全テナントで data_type='text' であること
```

### Step 4: 実機 IG webhook 受信の確認

しんごさんに IG DM を再送依頼し、`meta_messages` に新規行が入ることを確認:

```sql
SELECT id, platform, message_id, length(message_id) AS mid_len, created_at
  FROM tenant_004.meta_messages
 WHERE platform = 'instagram'
 ORDER BY id DESC
 LIMIT 5;
```

`mid_len > 100` の行が **エラーなく** INSERT されていれば成功。

---

## ロールバック手順

> **重要**: down migration は安全側で設計されており、`message_id` の最大長が
> 100 を超える行が 1 行でも存在すれば失敗する（Q-026.2 / 自動 truncate 禁止）。

### Step R-1: 100 文字超過行の有無を確認

```sql
-- 各テナントで実行
SELECT id, length(message_id) AS len
  FROM tenant_004.meta_messages
 WHERE length(message_id) > 100;
```

### Step R-2-A: 100 文字超過行が無い場合（down 可能）

```bash
# psql で down 用 SQL の {schema} を手動置換して実行
# 例: tenant_004 の場合
sed 's/{schema}/tenant_004/g' \
  /app/migrations/052_alter_meta_messages_message_id_to_text_down.sql \
  | docker compose exec -T db psql -U salesanchor -d salesanchor
```

期待出力:

```text
NOTICE: migration 052 down: tenant_004.meta_messages.message_id altered back
        to VARCHAR(100) (max observed length=NN)
```

### Step R-2-B: 100 文字超過行がある場合（down 不可、運用判断）

down migration はそのまま実行すると `RAISE EXCEPTION` で失敗する。
選択肢:

1. **そのまま稼働継続** — TEXT のままで運用上の問題はない（推奨）。
2. **超過行を別テーブルに退避してから down** — 履歴上どうしても
   VARCHAR(100) に戻したい場合のみ。手順:
   ```sql
   -- 退避
   CREATE TABLE tenant_004.meta_messages_long_mid_backup AS
   SELECT * FROM tenant_004.meta_messages
    WHERE length(message_id) > 100;
   -- 削除
   DELETE FROM tenant_004.meta_messages WHERE length(message_id) > 100;
   -- down migration を再実行
   ```
   削除は IG メッセージ履歴の破壊的操作なので、必ず Hitoshi の明示承認を
   得てから実施すること。

---

## 関連リンク

- [ADR-026](../adr/ADR-026_meta_messages_message_id_text.md)
- 既存定義: `migrations/013_add_meta_webhook_idempotency.sql`,
  `migrations/041_extend_meta_messages.sql`
- per-tenant スクリプト雛形: `scripts/migrate_meta_page_routing.py`
- 切り分けメモ:
  `~/.claude/projects/-Users-hitoshi-Documents---------------CRM----/memory/project_ig_webhook_message_id_truncation.md`
- regression test: `backend/tests/test_webhook_instagram.py::test_long_message_id_persists`
