# scripts/_archive/data_migration/

Phase 1-B-2 Step 5d / PR γ で archive 化した使い切りデータ移行スクリプト。

## 経緯

| ファイル | 役割 | 最後に動いた工程 |
|---|---|---|
| `migrate_customers_from_sheet.py` | Sheet → customers の旧 1:1 ロード | Phase 1 再設計 (2026-04-23) |
| `verify_customers_migration.py` | 上記の事後検証 | Phase 1 再設計 (2026-04-23) |
| `migrate_companies_contacts_from_customers.py` | customers → (companies, contacts) 1:N 分解 + `_customer_migration_map` 投入 | Phase 1-B-2 Step 3 (2026-04-24) |
| `verify_companies_contacts_migration.py` | 上記の事後検証 (11 項目) | Phase 1-B-2 Step 3 (2026-04-24) |
| `verify_downstream_fk_migration.py` | deals/orders/quotes/invoices.customer_id ↔ company_id/contact_id 整合性 | Phase 1-B-2 Step 4 (2026-04-24) |

## 実行不可な理由

migration 035 (PR β #155) で `customer_id` 列が、migration 036 (PR γ) で `_customer_migration_map`
テーブルが本番から DROP 済。これらのスクリプトはどちらにも依存しているため、Step 5d 適用後の
DB スキーマでは SQL レベルで失敗する。

## 関連 archive workflow

- `.github/workflows/_archive/run-phase1-b2-step3-migration.yml`
- `.github/workflows/_archive/verify-phase1-b2-step4-migration.yml`

両 workflow とも `workflow_dispatch` の手動トリガー専用だったため、`.github/workflows/`
直下から外したことで GitHub Actions UI には出てこなくなる。

## 復活させたい場合

万が一 customers テーブルベースの過去データを再投入する必要が生じた場合、本スクリプトを
そのまま動かすことはできない（DB 側の前提が消えている）。新規スクリプトを別途設計するか、
移行時点の pg_dump を別 DB にロードして調査する。
