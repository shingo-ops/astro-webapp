# ADR-026: meta_messages.message_id の TEXT 化（Instagram mid 受信対応）

- **Status**: Proposed
- **Date**: 2026-05-13
- **Deciders**: Shingo Tanizawa (PO)
- **関連 ADR**: ADR-012（What/How 役割分担）, ADR-024（Meta 連携の構造的不整合の修正）, ADR-025（Meta 連携の運用整備強化）

---

## Context

ADR-024 + ADR-025 で Meta 連携の構造的不整合と運用整備を完了し、Webhook 受信フローは Messenger 側で動作確認済み（2026-05-13）。しかし、Instagram DM 受信は実体として動作しておらず、Inbox に IG メッセージが 1 件も表示されない事象を 2026-05-13 に切り分けた結果、以下の真因を特定:

**`meta_messages.message_id` カラムが `VARCHAR(100)` で定義されているが、Instagram の Message ID（mid）は base64 多重エンコードで 150〜200 文字を超え、PostgreSQL の `StringDataRightTruncationError` で INSERT が全件失敗していた。**

エラーログ実体（2026-05-13 取得）:

```
sqlalchemy.exc.DBAPIError: asyncpg.exceptions.StringDataRightTruncationError:
value too long for type character varying(100)

[parameters: (4, 2, 'instagram', '2285523158643000',
'Test after curl re-subscribe by Instagram - May.13 14:47', ...
'aWdfZAG1faXRlbToxOklHTWVzc2FnZAUlEOjE3ODQxNDY2ODY5MzU4MDIzOjM0MDI4MjM2Njg0...',  # 157 文字
'664490526747447')]
```

### 確認済みの正常項目（受信フローの他箇所は完璧）

- ✅ `tenant_meta_config`: page_id=664490526747447 / instagram_business_account_id=17841466869358023 / instagram_username=treasureislandjapan / is_active=t
- ✅ `public.meta_page_routing`: page_id + ig_id 両方 tenant_id=4 で登録
- ✅ `webhook.py` の IG 分岐 / `_resolve_page_id_for_ig` / `_iter_inbound_messages` (messaging[]/changes[] 両形式) すべて実装済
- ✅ ADR-024 AC-1 で IG 側 `subscribed_apps` 明示 subscribe、AC-2 で verification 実装済
- ✅ Meta は IG webhook を VPS に POST してきており、backend は INSERT を試行している（log 確認済）

### 定義箇所

- `migrations/013_add_meta_webhook_idempotency.sql:34` — `meta_messages.message_id VARCHAR(100)`
- `migrations/041_extend_meta_messages.sql:45` — 同上（重複定義、idempotent）

### 影響範囲

- Messenger の mid は短い（10〜30 文字）ため影響なし。既存稼働中の受信フローは無傷
- Instagram のみ全件 INSERT 失敗 = Inbox の IG タブが永続的に空
- ON CONFLICT DO NOTHING より前の型変換ステージで失敗するため、`message_id` を null 化する fallback も効かない

## What

以下の状態を実現する：

1. **カラム型の拡張**: `meta_messages.message_id` を `VARCHAR(100)` から `TEXT` 型に変更（VARCHAR(255) ではなく `TEXT` を採用、Meta の将来仕様変更耐性のため）
2. **per-tenant 適用スクリプト**: 全 active テナント schema (`tenant_001`〜`tenant_NNN`) の `meta_messages` テーブルに ALTER を一括適用する Python スクリプトを整備（`scripts/migrate_meta_page_routing.py` パターン踏襲）
3. **Down migration**: 既存データに 100 文字超の `message_id` が存在しない場合のみ VARCHAR(100) に戻せる down migration を提供（truncation リスクのため警告コメント付き）
4. **regression test**: 157 文字超の `message_id` を含む Instagram webhook payload で `_persist_meta_message` が成功することを確認する pytest を追加
5. **検証ステップ**: 適用後に既存 IG webhook が DB に正常 INSERT されることを実機で確認する手順を整備

## Why

- **Phase 1 (Meta App Review 通過) の直接的な阻害要因**: IG 受信は Phase 1 必須要件、Inbox に IG メッセが表示されない状態では App Review 撮影シーン 7（Instagram DM 受信）が成立しない
- **既存 Messenger フローへの影響なし**: ALTER COLUMN TYPE で `VARCHAR(100) → TEXT` は PostgreSQL で **データ無損失の lossless 変換**、既存行・index に影響を与えない（オンライン ALTER 可能）
- **Meta の Instagram mid 仕様**: Meta は IG の mid に base64 多重エンコード（page-scoped + thread-scoped + timestamp）を採用しており、長さは仕様上 200 文字を超える可能性も
- **TEXT 採用の根拠**: `VARCHAR(255)` でも当面足りるが、将来の Meta API バージョンアップで mid 長が拡張された場合に再度 migration が必要になる。`TEXT` なら長さ制約なし、PostgreSQL では `TEXT` と `VARCHAR` のパフォーマンス差はほぼ無視できる
- **ADR-025 の検証スクリプト 3 点セット原則の遵守**: 機能修正本体 + 検証 (regression test) + 監視 (今回は per-tenant 適用スクリプトの dry-run + 実機確認) を併設

## Scope 外

- `meta_messages` テーブルの他カラム拡張（`sender_id`、`raw_payload` 等は現状 VARCHAR 制約を超えない）
- Messenger 側受信フローの変更（既に稼働中、無傷で維持）
- IG 受信時の通知文言の変更（Discord 通知メッセージは既存のまま）
- 既存の `message_id` が VARCHAR(100) に収まっている過去レコードへの遡及処理（不要、新規 INSERT のみ影響）
- ADR-021 関連で発覚した `column s.is_employee does not exist` エラー（別 Issue / 別 ADR で対応、本 ADR の Scope 外）
- Page Access Token の rotation や OAuth フロー変更
- 撮影シーン 4（Inbox からの返信送信）の動作検証（送信側は本 ADR と独立、別途要検証）

## 事業上の制約

- **Meta App Review 撮影の前提条件**: 本 ADR の実装完了まで撮影シーン 7（Instagram DM 受信）は再開不可
- **既存稼働への影響最小化**: ALTER COLUMN は本番稼働中の `meta_messages` に対するスキーマ変更、適用中の write ロックは秒オーダー（オンライン ALTER で済む）
- **per-tenant 適用の冪等性**: スクリプトは複数回実行しても安全であること（既に TEXT 化されている tenant schema は skip）
- **rollback 可能性**: 万一の不具合時に migration 052 を down できること（ただし `message_id` の長さに 100 を超える行があれば down 失敗、警告ログを出す）
- **既存 regression test の継続成功**: `tests/test_webhook_instagram.py` の既存 test が引き続き pass すること

## 受け入れ条件（実装完了の判定基準）

### Migration

1. `migrations/052_alter_meta_messages_message_id_to_text.sql` を新規作成。`ALTER TABLE meta_messages ALTER COLUMN message_id TYPE TEXT;` を含む。各 tenant schema での適用が必要であるためコメントで明記
2. `migrations/052_alter_meta_messages_message_id_to_text_down.sql` を新規作成。`message_id` 列の最大長が 100 以下である場合のみ VARCHAR(100) に戻す（事前 SELECT で MAX(length(message_id)) <= 100 を確認するコメント付き）
3. `scripts/migrate_meta_messages_message_id_to_text.py` を新規作成、全 active tenant schema に対して migration 052 を冪等的に適用。`scripts/migrate_meta_page_routing.py` の構造を踏襲

### Regression Test

4. `tests/test_webhook_instagram.py` に新規 test ケースを追加: 157 文字以上の `message_id` を含む IG webhook payload を POST し、`meta_messages` への INSERT が成功することを assert
5. 既存の Messenger / Instagram webhook test が引き続き pass する

### 検証手順

6. `docs/operations/meta_messages_message_id_text_migration.md`（or 簡易な README 追記）に以下を記載:
   - 適用前の SQL チェック（`SELECT MAX(length(message_id)) FROM ... .meta_messages`）
   - スクリプト実行コマンド
   - 適用後の確認 SQL（`\d+ meta_messages` で `message_id` が `text` 型になっていること）
   - rollback 手順（down migration の適用条件と注意点）

### Pipeline 実行

7. Generator → Evaluator → Reviewer (auto pipeline) が全て pass
8. Reviewer APPROVED の状態で develop に squash merge
9. develop → main の手動 merge 後、VPS に migration 052 適用、IG webhook 受信が成功することを実機で 1 件以上確認

## Open Questions

すべて即決可能、Generator 着手前の Hitoshi 即決事項として以下を確定:

- **Q-026.1**: 型は `TEXT` か `VARCHAR(255)` か → **TEXT 採用**（Meta 仕様変更耐性 + VARCHAR との差なし）
- **Q-026.2**: down migration で長さ超過行があった場合の挙動 → **失敗させる（truncate しない、安全側）**
- **Q-026.3**: スクリプトの冪等性確認 → **`information_schema.columns` で `data_type='text'` を事前確認、既に TEXT なら skip**
- **Q-026.4**: regression test の payload で IG の本物 mid を使うか架空文字列で 157 文字を作るか → **架空文字列で 200 文字（境界より十分長く）を作る**（本物 PII を test fixture に置かない）

## 関連リンク

- 切り分けログ: `~/.claude/projects/-Users-hitoshi-Documents---------------CRM----/memory/project_ig_webhook_message_id_truncation.md`
- 既存 migration: `migrations/013_add_meta_webhook_idempotency.sql`, `migrations/041_extend_meta_messages.sql`
- 既存 per-tenant migration スクリプト雛形: `scripts/migrate_meta_page_routing.py`
- ADR-024 (Meta 連携構造的不整合の修正): `docs/adr/ADR-024_meta_integration_structural_fix.md`
- ADR-025 (Meta 連携運用整備強化): `docs/adr/ADR-025_meta_integration_operational_hardening.md`
