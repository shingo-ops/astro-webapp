# Phase 1-B-2 Step 5d 実装計画 (v2)

- 作成日: 2026-04-27
- 作成者: Claude (Generator agent)
- ステータス: **PR α 実装中（feature/morimoto/step5d-code-cleanup）**
- 目的: 旧 `customer_id` 列・`_customer_migration_map`・`customer_resolver.py` を完全撤去し、新 B2B モデル (company_id + contact_id) を「唯一の正」にする
- 関連 PR: #147 / #149 / #150 (Step 5c-3 と follow-up)
- 関連 migration: 028-034

---

## 0. TL;DR（しんごさん向け）

- 影響範囲: backend Python 7 ファイル / frontend TS 7 ファイル / migration 2 本新規 / preflight script 1 本 / tests SQLite schema 修正 / `tenant.py` (1 ファイル) — 合計 **約 18 ファイル**
- migration 035 で `customer_id` 列を物理削除、036 で `_customer_migration_map` を削除（**分けてある**のは安全策）
- **適用順序は推奨 A**: 「コード切替 PR を main マージ → 本番反映 → preflight script で全テナント PASS 確認 → migration 035 適用 → 1 週間安定確認 → migration 036 適用」
- 適用前には `scripts/preflight_step5d.sh` を VPS で必ず実行すること
- ロールバック: 035 適用後の rollback は **pg_dump 復元が正攻法**（列の値は失われるため）

---

## 1. 影響範囲調査

### 1.1 backend (Python) — `customer_id` を直接参照しているファイル

| ファイル | 出現数 | 種類 | Step 5d での扱い |
|---|---:|---|---|
| `backend/app/services/customer_resolver.py` | 全文 | モジュール本体 | **削除** |
| `backend/app/services/tenant.py` | 9 箇所 | schema 自動生成 (deals/orders/quotes/invoices) | `customer_id` 列定義削除 + `_customer_migration_map` 削除 |
| `backend/app/routers/deals.py` | 約 25 箇所 | create / update / list / response | resolver 呼び出し削除、`customer_id` 列削除、validator 削除 |
| `backend/app/routers/orders.py` | 約 11 箇所 | create / list / response | 同上 |
| `backend/app/routers/quotes.py` | 約 11 箇所 | create / list / response | 同上 |
| `backend/app/routers/invoices.py` | 約 12 箇所 | create / list / from-quote | resolver は導入されていない → 直接 contact_id ベースに書き換え |
| `backend/app/routers/leads.py` | 約 7 箇所 | convert | resolver 呼び出し削除 |
| `backend/app/routers/customers.py` | 67 箇所 | customers サブテーブル (addresses/sales_channels/discord/contact_channels) のキー | **触らない**（customers テーブル自体は archive 扱いで残す） |
| `backend/app/routers/erp.py` | 2 箇所 | invoices.customer_id を JOIN | invoices.customer_id 削除に伴い JOIN 経路を company_id 経由に書き換え |
| `backend/app/routers/duplicates.py` | 2 箇所 | for table, col in [(...)]: チェック | リスト要素から削除 |
| `backend/app/routers/analytics.py` | 4 箇所 | dashboard 集計 SELECT | customer_id を含む SQL を company_id ベースに書き換え |
| `backend/app/routers/dashboard.py` | 6 箇所 | TYPE 定義 + 集計 SQL | 同上 |
| `backend/app/tasks/reports.py` | 6 箇所 | reports JOIN | customer_id JOIN を company_id JOIN に置換 |
| `backend/app/schemas/deal.py` | 4 箇所 | DealCreate / DealUpdate / DealResponse / model_validator | `customer_id` field 削除、`_require_customer_or_contact` validator → contact_id 単独必須 |
| `backend/app/schemas/order.py` | 4 箇所 | 同上 | 同上 |
| `backend/app/schemas/quote.py` | 4 箇所 | 同上 | 同上 |
| `backend/app/schemas/invoice.py` | 2 箇所 | InvoiceCreate (`customer_id: int = Field(ge=1)`) / InvoiceResponse | `customer_id` 必須 → 削除、`contact_id` 必須に置換 |
| `backend/app/schemas/lead.py` | 4 箇所 | LeadConvertRequest / Response | `customer_id` field 削除、validator 撤去 |

**backend/tests** (97 箇所、6 ファイル):
- `tests/conftest.py` — SQLite テーブル定義の `customer_id INTEGER REFERENCES customers(id)` 行 9 箇所を削除（`deals` / `orders` / `quotes` / `invoices` の test schema）
- `tests/test_deals.py`, `test_orders.py`, `test_security.py`, `test_dashboard.py`, `test_customers.py` — `customer_id` ベースの POST body を `contact_id` ベースに書き換え

### 1.2 frontend (TypeScript) — 7 ファイル / 10 行

| ファイル | 行 | 用途 | Step 5d での扱い |
|---|---:|---|---|
| `pages/DealsPage.tsx` | 25 | `interface Deal { customer_id: number\|null }` | 削除 |
| `pages/DealsPage.tsx` | 72 | コメント | 「Step 5d で削除済」に更新 |
| `pages/DealsPage.tsx` | 168-185 | レガシー deal (`company_id == null && contact_id != null`) ハンドリング | 削除（Step 5d 時点では本番に存在しないはず → preflight で確認） |
| `pages/OrdersPage.tsx` | 8 | `interface Order { customer_id: number }` | 削除 |
| `pages/OrdersPage.tsx` | 31 | コメント | 「Step 5d で `customer_id` 廃止」に更新 |
| `pages/QuotesPage.tsx` | 18 | interface | 削除 |
| `pages/QuoteDetailPage.tsx` | 27 | interface | 削除 |
| `pages/InvoicesPage.tsx` | 15 | interface | 削除 |
| `pages/InvoiceDetailPage.tsx` | 27 | interface | 削除 |
| `components/CompanyContactSelector.tsx` | 4, 14 | コメント | 「Step 5d で legacy customer_id は廃止済」に更新 |

frontend は **送信側はすでに company_id/contact_id ベースに切替済み**（Step 5c-3 で完了）。表示側のレスポンス型に `customer_id: number` が残っているだけ。Step 5d では純粋に「型から削るだけ」のクリーンアップ。

### 1.3 scripts (Python migration tools) — 5 ファイル

| ファイル | 影響 |
|---|---|
| `scripts/data_migration/migrate_companies_contacts_from_customers.py` | 旧 customers → companies/contacts の移行スクリプト。本番では既に実行完了。**残すが README で「Step 5d 以後は使えない」と注記**するか、移動して `archive/` 化する |
| `scripts/data_migration/verify_companies_contacts_migration.py` | 同上 |
| `scripts/data_migration/verify_downstream_fk_migration.py` | 「`customer_id` 有 → `company_id`/`contact_id` も有」検証。Step 5d で `customer_id` が消えるとロジック自体が無意味 → archive 化 |
| `scripts/data_migration/migrate_customers_from_sheet.py` | Sheet → customers の旧経路。company/contact ベースの新スクリプトは既に別所にあるはず。**archive 化**を推奨 |
| `scripts/data_migration/verify_customers_migration.py` | 同上 |

### 1.4 DB レベルの FK / INDEX

migration 032 で追加された FK:
- `fk_deals_company` / `fk_deals_contact` — 残す
- `fk_orders_company` / `fk_orders_contact` — 残す
- `fk_quotes_company` / `fk_quotes_contact` — 残す
- `fk_invoices_company` / `fk_invoices_contact` — 残す

`DROP COLUMN customer_id CASCADE` で連動削除されるもの:
- 暗黙の FK（`customers.id` 参照）— `customer_id REFERENCES {schema}.customers(id)` の各テーブル
- 暗黙の INDEX（あれば。明示的な `idx_*_customer_id` は **存在しない**ことを確認済）

`v_senders` などの VIEW は customer 系を参照していないため影響なし。

### 1.5 過去の external review に明記された「Step 5d でやるべき」項目

- **PR #147 N5** — 「VPS で `SELECT count(*) FROM deals WHERE company_id IS NULL` が 0 件か確認してから本番デプロイ」 → preflight script に組込済
- **PR #150 round2 FU-1** — `tenant.py` の `_customer_migration_map.new_contact_id` を column-inline UNIQUE → named CONSTRAINT `uniq_cmm_new_contact_id` に変更 → migration 036 で `_customer_migration_map` を drop するため自動的に解決
- **PR #150 round2 FU-2** — `verify_companies_contacts_migration.py` に「new_contact_id 重複 0 件」assert 追加 → 本 plan の preflight script で代替（verify script を更新するなら別 PR でも可）
- **PR #150 round2 FU-2** — `tenant.py` 内の `_customer_migration_map` ブロックと `customer_resolver.py` をまとめて削除 → 本 plan の backend コード変更計画に明記

---

## 2. Migration 草案

### 2.1 ファイル一覧（書いたが commit していない）

- `migrations/035_drop_customer_id_from_downstream.sql` — `customer_id` 列を DROP
- `migrations/036_drop_customer_migration_map.sql` — `_customer_migration_map` テーブルを DROP
- `scripts/preflight_step5d.sh` — 適用前 VPS 健全性チェック

**035 と 036 を分離した理由**:
- 035 適用直後に問題発覚した場合、`_customer_migration_map` が残っていれば手動 DOWN migration の参照ソースに使える（`contact_id → 旧 customer_id` の逆引き）
- 035 が 1 週間以上安定稼働してから 036 を流す運用にすれば、「列を一時的に戻したい」緊急時に備えられる

### 2.2 035 の SQL 概要

```sql
-- precondition phase（FAIL なら EXCEPTION）
-- 全 tenant_NNN スキーマで:
--   deals.company_id IS NULL の COUNT == 0
--   orders.company_id IS NULL の COUNT == 0
--   quotes.company_id IS NULL の COUNT == 0
--   invoices.company_id IS NULL の COUNT == 0
-- いずれか > 0 なら failed_schemas に蓄積して RAISE EXCEPTION

-- main phase
-- ALTER TABLE ... ALTER COLUMN company_id SET NOT NULL  （deals/orders は元 nullable）
-- ALTER TABLE ... DROP COLUMN IF EXISTS customer_id    （FK と暗黙 INDEX が連動削除）
```

### 2.3 036 の SQL 概要

```sql
-- precondition: 全 tenant の deals/orders/quotes/invoices に customer_id 列が無い
--   （035 適用済みの保証）
-- main: DROP TABLE IF EXISTS {schema}._customer_migration_map CASCADE
```

### 2.4 冪等性

両 migration とも `IF EXISTS` / `IF NOT EXISTS` で再実行 no-op。precondition が失敗した場合は EXCEPTION で停止し、副作用なし。

### 2.5 DOWN migration

両 migration とも DOWN 用 SQL を **末尾コメント** に記載。ただし:
- 035 DOWN: 列だけ復活する。値は失われている（→ pg_dump 復元が正攻法）
- 036 DOWN: テーブルごと失われたら再生成不可（→ pg_dump 復元のみ）

---

## 3. Backend コード変更計画（diff スケッチ）

### 3.1 `backend/app/schemas/deal.py`

```diff
 class DealCreate(BaseModel):
-    customer_id: int | None = Field(default=None, ge=1, description="顧客ID（旧モデル、Step 5d まで維持）")
-    company_id: int | None = Field(default=None, ge=1, description="会社ID（新モデル）")
+    company_id: int = Field(ge=1, description="会社ID")
-    contact_id: int | None = Field(default=None, ge=1, description="担当者ID（新モデル）")
+    contact_id: int = Field(ge=1, description="担当者ID")
     ...

-    @model_validator(mode="after")
-    def _require_customer_or_contact(self) -> "DealCreate":
-        if self.customer_id is None and self.contact_id is None:
-            raise ValueError("customer_id または contact_id のいずれかは必須です")
-        return self

 class DealUpdate(BaseModel):
-    customer_id: int | None = Field(default=None, ge=1)
     # 残りは変化なし

 class DealResponse(BaseModel):
     id: int
     deal_code: str | None
-    customer_id: int | None
-    company_id: int | None = None
+    company_id: int
-    contact_id: int | None = None
+    contact_id: int
     ...
```

`order.py` / `quote.py` / `invoice.py` / `lead.py` も同様。

### 3.2 `backend/app/routers/deals.py`

```diff
-from app.services.customer_resolver import resolve_customer_id

 _DEAL_COLUMNS = """
-    id, deal_code, customer_id, company_id, contact_id, lead_id,
+    id, deal_code, company_id, contact_id, lead_id,
     ...
 """
 _UPDATABLE_COLUMNS = {
-    "customer_id", "company_id", "contact_id", "lead_id",
+    "company_id", "contact_id", "lead_id",
     ...
 }

 async def create_deal(...):
-    customer_id = data.customer_id
-    if customer_id is None:
-        customer_id = await resolve_customer_id(db, data.contact_id, data.company_id)
-    else:
-        # 旧経路（30行）...
+    # 新経路だけ残す: contact / company の存在 + 所属一致確認
+    contact_check = await db.execute(text("SELECT company_id FROM contacts WHERE id = :id"), {"id": data.contact_id})
+    contact_row = contact_check.first()
+    if not contact_row:
+        raise HTTPException(404, "指定された担当者が見つかりません")
+    if contact_row[0] != data.company_id:
+        raise HTTPException(400, "指定された担当者は指定会社に所属していません")
     # INSERT 文から customer_id を削除
     # ...

 async def update_deal(...):
     # has_customer_update / customer_id 関連分岐をすべて削除
     # has_company_update / has_contact_update のみで検証
```

### 3.3 `backend/app/routers/invoices.py`

```diff
 async def create_invoice(data: InvoiceCreate, ...):
-    cust = await db.execute(text("SELECT id FROM customers WHERE id = :id"), {"id": data.customer_id})
-    if not cust.first():
-        raise HTTPException(404, "指定された顧客が見つかりません")
+    # contact_id ベースで存在確認
+    contact_check = await db.execute(text("SELECT company_id FROM contacts WHERE id = :id"), {"id": data.contact_id})
+    contact_row = contact_check.first()
+    if not contact_row:
+        raise HTTPException(404, "指定された担当者が見つかりません")
+    if contact_row[0] != data.company_id:
+        raise HTTPException(400, "担当者と会社の所属が不一致")

     # INSERT 文から customer_id 削除
```

`from_quote/{quote_id}` 経路は元々 quote から company_id/contact_id を継承していたので、`q["customer_id"]` 参照を削るだけ。

### 3.4 `backend/app/services/customer_resolver.py`

**ファイルごと削除**。

### 3.5 `backend/app/services/tenant.py`

```diff
 CREATE TABLE IF NOT EXISTS {schema}.deals (
     id SERIAL PRIMARY KEY,
     ...
-    customer_id INTEGER REFERENCES {schema}.customers(id),
-    company_id INTEGER CONSTRAINT fk_deals_company REFERENCES {schema}.companies(id),
+    company_id INTEGER NOT NULL CONSTRAINT fk_deals_company REFERENCES {schema}.companies(id),
     contact_id INTEGER CONSTRAINT fk_deals_contact REFERENCES {schema}.contacts(id),
     ...
 );
```

`orders` / `quotes` / `invoices` も同様。`_customer_migration_map` の CREATE TABLE ブロックは丸ごと削除。

### 3.6 `backend/app/routers/duplicates.py:176-177`

```diff
-for table, col in [("deals", "customer_id"), ("orders", "customer_id"),
-                   ("quotes", "customer_id"), ("invoices", "customer_id")]:
+for table, col in [("deals", "company_id"), ("orders", "company_id"),
+                   ("quotes", "company_id"), ("invoices", "company_id")]:
```

ただしこれは「重複検出」のロジックなので、本当に必要かは仕様確認が必要（重複は company_id 単位なのか contact_id 単位なのか）。

### 3.7 `backend/app/routers/analytics.py` / `dashboard.py` / `tasks/reports.py`

JOIN 経路を `customers` → `companies` に書き換え:

```diff
-LEFT JOIN customers c ON d.customer_id = c.id
-LEFT JOIN customer_addresses ba ON ba.customer_id = c.id AND ba.address_type = 'billing'
+LEFT JOIN companies c ON d.company_id = c.id
+LEFT JOIN company_addresses ba ON ba.company_id = c.id AND ba.address_type = 'billing'
```

ここは `companies` 系のサブテーブル名 (例: `company_addresses`) が存在するか確認が必要。**もし無ければ analytics/dashboard 側を「会社情報を含む請求書/注文表示」だけ簡略化するか、または customers サブテーブルを残すか、後者の方が現実的**。

### 3.8 `backend/tests/conftest.py`

SQLite テスト schema から `customer_id INTEGER REFERENCES customers(id)` 行を 9 箇所削除。`tests/test_deals.py` 等は `customer_id=customer_id` を `company_id=company_id, contact_id=contact_id` ベースに書き換え（合計 97 箇所）。これは**最も労力が大きい**部分。

---

## 4. Frontend コード変更計画（diff スケッチ）

### 4.1 `frontend/src/pages/DealsPage.tsx`

```diff
 interface Deal {
   id: number;
   deal_code: string | null;
-  customer_id: number | null;
-  company_id: number | null;
-  contact_id: number | null;
+  company_id: number;
+  contact_id: number;
   ...
 }

-  // PR #147 F2: レガシー deal（company_id NULL）編集中フラグ
-  const [editingLegacyDeal, setEditingLegacyDeal] = useState(false);

   const handleEdit = async (d: Deal) => {
-    // PR #147 F2: レガシー deal（company_id NULL）の編集 UX 改善（18 行）
-    const isLegacy = d.company_id == null;
-    setEditingLegacyDeal(isLegacy);
-    if (isLegacy && d.contact_id != null) { ... }
-    else {
       setCompanyId(d.company_id);
       setContactId(d.contact_id);
-    }
     ...
   };
```

### 4.2 `OrdersPage.tsx` / `QuotesPage.tsx` / `QuoteDetailPage.tsx` / `InvoicesPage.tsx` / `InvoiceDetailPage.tsx`

`customer_id: number` 行を削除するだけ（送信ロジックは既に company/contact ベース）。

### 4.3 `CompanyContactSelector.tsx`

コメントを更新するだけ:

```diff
- * deals/quotes/orders/leads.convert の各フォームで顧客（旧 customer_id）の代わりに
+ * deals/quotes/orders/leads.convert の各フォームで顧客の選択に使う共通コンポーネント。
- * backend は Step 5c-3 で customer_id 未指定時に contact_id から _customer_migration_map で
- * 逆引きする。Step 5d で customer_id 列が drop されたら、本コメントも更新する。
+ * Step 5d で旧 customer_id 系統は完全撤去済み。新 B2B モデル (company + contact) のみ。
```

---

## 5. 本番適用前チェックリスト（VPS 上で実行する SQL）

`scripts/preflight_step5d.sh` がこれらを自動化していますが、人間が目視確認する場合の SQL は次の通り:

### 5.1 必須 PASS 条件（FAIL なら 035 適用 NG）

```sql
-- 各テナントスキーマで実行
SET search_path TO tenant_004;  -- 順次切替

-- 1) company_id NULL の行が 0 件
SELECT 'deals.company_id IS NULL' AS check, COUNT(*) FROM deals WHERE company_id IS NULL
UNION ALL SELECT 'orders.company_id IS NULL', COUNT(*) FROM orders WHERE company_id IS NULL
UNION ALL SELECT 'quotes.company_id IS NULL', COUNT(*) FROM quotes WHERE company_id IS NULL
UNION ALL SELECT 'invoices.company_id IS NULL', COUNT(*) FROM invoices WHERE company_id IS NULL;

-- 2) customer_id あり / contact_id なし の不整合（Step 5c-3 で resolver が走らなかった経路の検出）
SELECT 'deals: cust有 contact無', COUNT(*) FROM deals WHERE customer_id IS NOT NULL AND contact_id IS NULL
UNION ALL SELECT 'orders: cust有 contact無', COUNT(*) FROM orders WHERE customer_id IS NOT NULL AND contact_id IS NULL
UNION ALL SELECT 'quotes: cust有 contact無', COUNT(*) FROM quotes WHERE customer_id IS NOT NULL AND contact_id IS NULL
UNION ALL SELECT 'invoices: cust有 contact無', COUNT(*) FROM invoices WHERE customer_id IS NOT NULL AND contact_id IS NULL;

-- 3) _customer_migration_map.new_contact_id 重複検出
SELECT new_contact_id, array_agg(old_customer_id), COUNT(*)
FROM _customer_migration_map
GROUP BY new_contact_id HAVING COUNT(*) > 1;

-- 4) uniq_cmm_new_contact_id 制約存在確認（migration 034 の効果）
SELECT conname FROM pg_constraint
WHERE conname = 'uniq_cmm_new_contact_id'
  AND connamespace = (SELECT oid FROM pg_namespace WHERE nspname = 'tenant_004');
```

### 5.2 全 4 テナントで確認するスキーマ

memory より、本番 VPS の active なテナントは:
- `tenant_004` (highlife-jpn) — 本番データ 52 名 + 担当者 4 名
- `tenant_NNN` × 3 — test 系（空 or サンプル）

`preflight_step5d.sh` は `pg_namespace` で `^tenant_\d+$` を全列挙するため、自動的に全テナント対象。

### 5.3 オプショナル: backup 確認

```bash
# Step 5d 適用直前に最新 pg_dump があることを確認
ls -la /var/backups/postgres/ | head -5
```

---

## 6. 適用順序プラン

### 候補 A（推奨）: 段階適用 — 最も保守的

1. **PR α: backend / frontend 旧経路削除** （別ブランチ `feature/morimoto/step5d-code-cleanup`）
   - schemas / routers / frontend のコード変更
   - tests 修正
   - ローカル + CI で全テスト PASS 確認
   - main マージ → develop マージ → VPS 反映（コンテナ再起動）
   - **この時点ではまだ DB 側の `customer_id` は残っており、コード経由では一切書き込まれない（INSERT 文に含めない）**

2. **本番監視期間（24-48h）**
   - 異常がないことを確認（dashboard / 注文受付 / 見積発行が正常）
   - audit_logs を見て `customer_id` への書込が止まっていることを確認

3. **VPS 上で `bash scripts/preflight_step5d.sh "$DATABASE_URL"`**
   - 全テナント PASS を確認

4. **PR β: migration 035 適用** （別ブランチ `feature/morimoto/step5d-migration-035`）
   - `migrations/035_*.sql` のみを含む
   - main マージ → VPS で `psql ... -f 035_*.sql`

5. **本番安定確認期間（最短 1 週間）**
   - 何も起きなければ最終ステップへ

6. **PR γ: migration 036 + tenant.py / customer_resolver.py 削除**
   - `migrations/036_*.sql`
   - `backend/app/services/customer_resolver.py` 削除
   - `backend/app/services/tenant.py` から `_customer_migration_map` ブロック削除
   - 関連 verify scripts を archive 化
   - main マージ → VPS で 036 適用 + コンテナ再起動

**メリット**: rollback 余裕が最大 / どの段階でもコード ↔ DB 整合性が保たれる
**デメリット**: 期間が長い（最短 9 日、現実 2 週間程度）

### 候補 B: 一括適用 — リスク受容型

1. PR で **コード変更 + migration 035 + 036 + tenant.py 削除** をまとめて 1 PR に
2. ステージング環境で full smoke test
3. main マージ → VPS で「コードデプロイ → preflight → 035 → 036 → 再起動」を 1 セッションで実行

**メリット**: 期間が短い（1-2 日）
**デメリット**: rollback が pg_dump 復元のみ（=ダウンタイム発生確実）。本番運用中の destructive 変更としてはリスクが高い

### 候補 C: ハイブリッド (035 と 036 を分けつつコードと migration はまとめる)

1. PR で「コード変更 + migration 035」をまとめる
2. 1-2 週間後に PR で「migration 036 + tenant.py / resolver 削除」

**メリット**: 期間が短い + rollback の「最終保険」（_customer_migration_map）は残す
**デメリット**: コード変更直後に DB 構造が変わるため、デプロイ時のオペレーション複雑度は B に近い

---

### 推奨は候補 A

理由:
- Step 5d は **本番 4 テナントの実データ**に直接効く destructive 変更
- 段階分けすることで preflight 失敗時の判断ポイントが増える
- 候補 A の Step 1-3（コード切替 + 監視）は逆順 (DB 先) では絶対できない順序
- migration 035 / 036 を分けるコストはほぼ無く、得られる安全マージンは大きい

---

## 7. 想定リスク と 対策

| リスク | 発生確率 | 影響 | 対策 |
|---|---|---|---|
| 本番に `company_id IS NULL` の deal/order/quote/invoice が残っている | 低（migration 032 で backfill 済） | 035 が precondition で停止、適用失敗 | preflight script で事前検出。問題行を手動で `UPDATE company_id = ...` で埋めてから再実行 |
| invoice の `customer_id` が `from_quote` 経路で残った行で NULL に書けない | 低（quote 経由も company_id を継承済み） | 035 適用時に `ALTER COLUMN company_id SET NOT NULL` で失敗 | preflight に「invoices.company_id IS NULL = 0」を含めている |
| `analytics.py` / `dashboard.py` の JOIN を companies 系に書き換える際に `company_addresses` 等が無い | 中（要確認） | 集計クエリが落ちる | コード切替 PR に分離して、ステージングで集計画面を全部叩く smoke test。なければ「customers サブテーブルを当面残す」判断に切替 |
| 035 適用中に書込が走り中途半端な状態になる | 低（DDL は短時間 + ロック） | 整合性破綻 | メンテナンスモードで 5-10 分の書込停止 + バックアップ取得 |
| frontend デプロイ前に backend だけ更新 → 古い frontend が `customer_id` を送信 → 404 / 422 | 中 | 一時的 UI エラー | backend の方が validator 緩いので一時的に旧 payload も通る／逆順デプロイ（frontend 先）で対応 |
| `_customer_migration_map` を信頼している外部スクリプト | 低 | スクリプト失敗 | 5.1 の grep 結果通り、外部参照は data_migration script のみ。これらは archive 化予定 |
| audit_logs に過去の `customer_id` 値が JSON で残る | 確実 | 害なし（JSON テキスト） | そのまま放置（読み取り時に客先で混乱の可能性 → README に注記） |

---

## 8. ロールバック計画

### 8.1 Step 5d の各段階での rollback 戦略

| 段階 | 失敗時の戻し方 |
|---|---|
| PR α (コード変更) merge 後、本番反映前に問題発覚 | コードを revert + redeploy。DB は無傷 |
| PR α 反映後、24-48h 監視中に異常発覚 | コード revert + redeploy。`customer_id` 列は残っているので old code が動く |
| migration 035 適用中に precondition 失敗 | EXCEPTION で停止、副作用なし。違反行を手動で修復 |
| migration 035 適用後、本番運用で問題発覚 | **基本は pg_dump 復元**。035 末尾の DOWN コメントで列だけ復活させても、値は失われている。`_customer_migration_map` がまだ残っていれば `UPDATE ... FROM _customer_migration_map WHERE contact_id = new_contact_id` で逆引き復元可能 |
| migration 036 適用後 | pg_dump 復元の一択 |

### 8.2 Backup ポリシー

- 035 適用直前に `pg_dump` で full backup を取得し、S3 にアップロード
- backup 名: `pre-step5d-migration-035-YYYYMMDD-HHMM.sql.gz`
- 7 日以上保持（候補 A の安定確認期間に合わせる）

### 8.3 緊急時の連絡先

- しんごさん本人（VPS root 権限保有）
- Hikky-dev (リードエンジニア = 自分)

---

## 9. テスト計画

### 9.1 ローカル

- `pytest backend/tests` 全 PASS
- frontend `vitest` 全 PASS
- `frontend npm run build` 成功
- `docker compose up` で全画面 smoke test

### 9.2 ステージング (もしあれば)

- VPS と同じ schema を持つステージング DB に migration 035 / 036 を順次適用
- 全 API エンドポイント (deals/orders/quotes/invoices/leads/dashboard/analytics) を叩く
- migration 適用前後で `EXPLAIN` 比較（INDEX 削除によるクエリプラン悪化が無いか確認）

### 9.3 本番反映後

- 24h 監視: error rate / latency / dashboard 集計値が migration 前と一致
- audit_logs の sample 抽出で、新 INSERT/UPDATE が `customer_id` を含まないことを確認
- 1 週間後に migration 036 を流す前にもう一度 preflight 実行

---

## 10. ファイル一覧（本 plan で作成 / 計画している成果物）

### 10.1 すでに作成済み（ワークツリー、未 commit）

- `astro-webapp/.claude-pipeline/step5d-plan.md` ← 本ファイル
- `astro-webapp/migrations/035_drop_customer_id_from_downstream.sql`
- `astro-webapp/migrations/036_drop_customer_migration_map.sql`
- `astro-webapp/scripts/preflight_step5d.sh`

### 10.2 別セッションで作成予定（しんごさん review 後）

- backend コード変更 (上記 7 ファイル) を含む PR
- frontend コード変更 (上記 7 ファイル) を含む PR
- backend tests 修正
- archive 化スクリプトの移動

---

## 11. オープン質問（しんごさん review で要確認）

1. **`analytics.py` / `dashboard.py` の集計 SQL を `companies` 系に書き換える際、`company_addresses` 等のサブテーブルは存在するか？**
   - 存在しなければ「customers サブテーブルは当面残す（archive 扱い）」が現実解
   - 確認 SQL: `\dt tenant_004.company_*`
2. **migration 035 と 036 を分けて 1 週間以上空ける運用は受け入れ可能か？**
   - 受け入れ不可なら候補 C（コードと 035 を一緒、036 を分離）に切替
3. **`scripts/data_migration/` の旧スクリプトは archive (移動) でよいか、それとも削除か？**
   - archive を推奨（過去の audit / 再現性のため）
4. **本番 VPS にメンテナンスモード（書込停止）を入れる運用は可能か？**
   - 035 適用中の整合性確保のため、5-10 分のメンテナンスを推奨

---

## 12. 重要ステートメント

- **Step 5d は本番に直接効く destructive 変更です。しんごさんの最終承認なしに commit / push / 適用しません。**
- 本 plan は v2。しんごさんの判断（候補 A 採用、archive 移動、業務時間外適用）を反映済み。

---

## 13. PR α 実装結果（2026-04-27）

### 13.1 ブランチ / コミット

- ブランチ: `feature/morimoto/step5d-code-cleanup`（develop 起点）
- 含めたコミット:
  - `feat(phase1-b2-step5d-α): backend schemas/routers から旧 customer_id 系統を撤去` (14 ファイル)
  - `feat(phase1-b2-step5d-α): frontend interface から旧 customer_id を撤去` (7 ファイル)
  - `feat(phase1-b2-step5d-α): backend tests を company_id + contact_id ベースに刷新`
  - 計画 doc / preflight script / migration 035・036 (3 ファイル) を **PR α に同梱**

### 13.2 PR α に含めないもの (PR β/γ で対応)

- migration 035 / 036 の **適用** (PR α では SQL ファイル同梱のみ、適用は別)
- `backend/app/services/customer_resolver.py` の削除（PR γ）
- `backend/app/services/tenant.py` から `_customer_migration_map` ブロック削除 (PR γ)
- `scripts/data_migration/*.py` の archive 移動 (PR γ)

### 13.3 smoke test 結果

実 pytest 環境は baseline で `app.auth.dependencies` AttributeError 故障があり (PR #147/#149 と同じく実行不可)。
本 PR α では Pydantic schemas + AsyncSession モックによる smoke test で代替検証:

- **Schema-level smoke test (24/24 PASS)**
  - DealCreate / OrderCreate / QuoteCreate / InvoiceCreate / LeadConvertRequest が `company_id` + `contact_id` を必須化
  - `customer_id` field が全 schema から削除されていることを model_fields で確認
  - DealUpdate / DealResponse の field set 確認
  - ge=1 範囲制約が引き続き有効

- **Router-level smoke test (15/15 PASS)**
  - create_deal / create_order が contact-mismatch (400) と missing contact (404) を正しく扱う
  - 各 router (deals/orders/quotes/invoices/leads) から `customer_resolver` import が削除済
  - 各 router の SQL コードに `customer_id` 参照が残っていない

合計: **39/39 PASS**

### 13.4 想定残課題（PR β/γ への引き継ぎ）

- PR β: `migrations/035_drop_customer_id_from_downstream.sql` を本番適用
  - 適用前に `bash scripts/preflight_step5d.sh "$DATABASE_URL"` で全テナント PASS 確認
  - 業務時間外（夜間）に実施、5-10 分のメンテモード推奨
- PR γ (035 適用 1 週間後):
  - `migrations/036_drop_customer_migration_map.sql` 適用
  - `backend/app/services/customer_resolver.py` 削除
  - `backend/app/services/tenant.py` から `_customer_migration_map` CREATE TABLE / INDEX ブロック削除
  - `scripts/data_migration/migrate_customers_from_sheet.py` 等を `scripts/data_migration/_archive/` へ移動

### 13.5 Frontend デプロイ時の注意点

- Step 5c-3 で frontend は既に `(company_id, contact_id)` のみを送信する形に切替済 (PR #147)。
- PR α merge 後、backend が古い frontend からの payload を受け取った場合:
  - `customer_id` キーは pydantic 既定 (`extra='ignore'`) で **黙って drop** される
  - 古い frontend が同時に `company_id` + `contact_id` を送れば動く（Step 5c-3 から既にそう）
  - 古い frontend が `company_id` を送らない場合は 422 で "company_id field required" を返す
- 結論: backend と frontend のデプロイ順は問わない。本番は frontend を先に reload しても問題なし、backend を先に reload しても (5c-3 配信後の frontend なら) 問題なし。
- 念のため、本番反映時は **backend → frontend の順** を推奨（安全側）。

---
