# ADR-089: `customers` テーブル廃止と `companies` への一元化

## Status
Accepted

## Date
2026-06-01

## Context（背景）

Sales Anchor には現在、同じ「取引先」概念を指す2つのテーブルが並存している。

| テーブル | 件数 | 役割 | 問題 |
|---|---|---|---|
| `customers` | 52件 | 請求先・配送先・Discord webhook・販売チャネルを持つ旧顧客マスタ | Phase 1 初期に作成。`companies` と二重管理 |
| `companies` | 49件 | 取引先の会社エンティティ（新設計） | `company_addresses`（`branch_name` / `is_default` 対応）・`contacts`（担当者）・`company_sales_channels` を持つ |

### 二重管理による具体的な問題

1. **SSOT違反**: 同一取引先（例: "YHT Card Shop"）が `customers.company_name` と `companies.name` の2か所に存在し、一方を更新しても他方が古くなる
2. **lead_id 未使用**: `customers.lead_id` は設計上リードと紐づける意図だったが、52件中0件しか設定されていない（リードが直接 customers に変換されていない）
3. **機能差**: `company_addresses` は `branch_name`・`is_default` を持ち複数店舗に対応しているが、`customer_addresses` にはこれらがなく劣化コピー
4. **UI混乱**: サブメニューに「顧客管理」と「顧客管理(旧)」が並存し、どちらを使うべきか不明確

### 廃止の安全性

- `deals` / `quotes` / `invoices` / `orders` はすべて **0件**（本番未使用）
- migration 028〜036 で下流テーブルの FK 切替（`customer_id` → `company_id`）は既に完了済み
- `customers` データは migration 031 の移行マップ経由で `companies` / `contacts` に既に移行済み

## Decision（決定）

`customers` テーブルおよび関連副テーブルを廃止し、`companies` に一元化する。

### 廃止対象テーブル（6テーブル）

- `customers`
- `customer_addresses`
- `customer_discord`
- `customer_sales_channels`
- `customer_contact_channels`
- `customers_legacy_{tenant_id}`（migration 015 で退避された旧データ）

### 新設テーブル（1テーブル）

- `company_discord`（会社レベルの Discord webhook。`customer_discord` の後継）

### データ移行方針

`customer_discord` のデータ（Discord webhook URL）は `company_discord` に移行してから `customers` を DROP する。

## Scope（スコープ）

### DB（migration）
- `company_discord` テーブルを新設（additive）
- `customer_discord` データを `company_discord` へ移行（INSERT INTO ... SELECT）
- 旧テーブル群を DROP（destructive・PO確認済み）

### Backend
- `routers/customers.py` を廃止
- `routers/duplicates.py` の `customers` 参照を `companies` ベースに書き換え
- `services/tenant.py` の新テナント作成時 customers テーブル CREATE ロジックを削除
- `routers/companies.py` に Discord webhook の CRUD を追加

### Frontend
- `CustomersPage.tsx`（`/crm/customers`）を廃止または `companies` にリダイレクト
- サブメニューから「顧客管理(旧)」を削除
- 会社詳細ページに Discord webhook タブ追加（`company_discord` 対応）

## Consequences（影響）

### ポジティブ
- 取引先データの SSOT が確立される
- `leads` → `companies` → `deals` のライフサイクルが完結する
- UI からの「旧」表記が消え、ユーザーの迷いがなくなる
- 維持する API が半分になる

### リスクと対策
- **destructive migration**: additive-only 原則の例外として PO 承認済み（本 ADR が承認証跡）
- **tenant.py への影響**: 新テナント作成フローのテストが必要
- **データ損失リスク**: deals/quotes/invoices/orders が全0件のため実質ゼロ。migration 実行前に COUNT チェックを挿入する

## 関連 ADR
- ADR-025: データ手動INSERT原則禁止
- ADR-034: テナント migration 自動化
- ADR-045: migration additive-only 原則
- ADR-060: companies → 「顧客情報」リネーム
