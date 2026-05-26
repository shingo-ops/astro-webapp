# ADR-034: 新規テナント migration 自動化 + 既存テナント整合化

| 項目 | 内容 |
|------|------|
| ステータス | Proposed (rev.2: 2026-05-27 スコープ拡大) |
| 初稿 | 2026-05-15 |
| 改訂 | 2026-05-27 — 本番 tenant_004 も migration 005 未適用が判明し、Scope を「全既存テナントのスキーマ整合化」まで拡大 |
| 関連 | ADR-028 (撮影テナント分離), ADR-036 (Tenant Schema Integrity Check), ADR-072 (テナント schema RBAC) |
| 影響範囲 | 本番 (tenant_004) を含む全テナント、新規テナント onboarding パイプライン |
| 緊急度 | High — 本番テナントが未整備のまま、機能を初めて触ると 500 が出る既知時限爆弾を抱えている |

## What

1. `deploy.yml` に「全テナントへの migration 適用ループ」を追加し、main push 時に各テナント schema へ idempotent migration が再走するようにする
2. 新規テナント作成スクリプト (`scripts/setup_tenant.py`) に「過去の全テナント migration を適用する」処理を追加する
3. **既存全テナント (tenant_001〜006) のスキーマ整合化** — `information_schema.columns` で baseline を満たしていないテナントに、欠落 migration を追加適用する
4. 全テナントのスキーマ整合性を `lint-tenant-schema.yml` (既存) で常時検証可能にし、新規 migration 追加時に「全テナント適用」が CI 強制されるようにする

## Why

### 2026-05-15 初稿時点 (tenant_006 onboarding で発覚)

撮影用 `tenant_006` 作成時に、過去 migration が自動適用されない設計欠陥が判明し、3 件を緊急手動修正:

1. `public.meta_page_routing` への自動登録欠落 → webhook が届かない
2. `tenant_006.meta_messages` の 9 カラム欠落 → Inbox が 500
3. `tenant_006.meta_messages.message_id` が VARCHAR(100) のまま → Instagram DM (172 文字) が保存できない

これらは全て「`tenant_006` が古いテンプレートで作成され、その後の migration が適用されていない」という同一原因。

### 2026-05-27 追加発覚 (本番 tenant_004 も同じ欠陥)

`/orders` 画面で 500 (`column o.invoice_id does not exist`) を撮影用 tenant_006 で確認 → 調査で **本番 `tenant_004` (highlife-jpn) も同じ欠陥** にハマっていることが判明:

| schema | orders 列数 | 本来 (tenant_001/003 と同じ) | 状態 |
|---|---|---|---|
| tenant_001 | 19 | 19 | OK |
| tenant_003 | 19 | 19 | OK |
| **tenant_004 (本番)** | **11** | 19 | NG — migration 005 未適用 |
| tenant_005 | 11 | 19 | NG |
| tenant_006 | 11 | 19 | NG |

本番 tenant_004 では `orders` だけでなく `invoices` / `quotes` / `products` / `shipping_zones` / `shipping_rates` / `invoice_items` / `quote_items` テーブル自体も未作成。これらの機能を本番運用で初めて触るとことごとく 500 が出る時限爆弾。

orders の `invoice_id` 等 8 カラムは 2026-05-27 緊急手動 ALTER で当日復旧したが、残りの未作成テーブル群と将来追加される migration への対応は本 ADR の実装が完了するまで継続的に発生する。

### ビジネスインパクト

- 本番 tenant_004 (HIGH LIFE JPN) で販売・財務系機能 (見積・請求・受注詳細・配送) を初めて触ると 500
- 新規クライアント onboarding でメッセージが届かない / 機能が動かないクレーム必至
- 撮影 / Meta App Review で機能が動かなくなるリスク
- 「動いている本番」が偶然今まで該当機能を実運用していないだけで救われていた

## Scope

### 対象に含める (rev.2 で拡大)

- 全既存テナント (tenant_001〜006) のスキーマ整合化 — `information_schema.columns` baseline 比較で差分検出 + 補完
- 全 migration の「idempotent 性」を担保する CI チェック追加
- 新規テナント作成時の全 migration 自動適用パイプライン
- `deploy.yml` の main push 時に全テナント migration 再走 (CI 時間を考慮した差分検出ベース)

### 対象外 (Out of Scope)

- スキーマ分離方式の変更 (現設計 PostgreSQL schema 分離を維持)
- Row Level Security への抜本移行 (ADR-072 で別途扱い)
- 過去 migration の歴史的差分の完全再現 (idempotent baseline で十分とする)
- `migrate_phase2.py` のような既に壊れている (Phase 1-B-2 後の `customer_id` 廃止と整合しない) スクリプトの修復 — 新パイプラインで置き換える

## 事業上の制約

- 既存本番 tenant_004 への適用は **段階的かつ可逆** に行う (1 テナント / 1 migration ごとに記録)
- migration は idempotent (`IF NOT EXISTS` / `ON CONFLICT DO NOTHING`) を必須化、新規 migration 追加時に CI で検証
- マージ判断は Shingo (PO) — 本番 DDL を含むため自動マージ禁止
- 本番適用前に staging-like テナント (tenant_005 など) で必ず dry-run

## 暫定運用 (本 ADR マージまで)

`backend/CLAUDE.md` §「新規テナント作成時の不変条件チェック」の 4 ステップ手順を継続。本 ADR マージ時に該当セクションを削除する (`[SELF-DESTRUCT-ADR-034]` コメント済)。

新規 migration 追加時は、SQL に加えて全既存テナントへの手動適用ステップを PR body に明記する。
