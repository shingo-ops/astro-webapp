# Phase 1-C: 商品マスタ（products）再設計

| 項目 | 内容 |
|------|------|
| ステータス | **Proposed**（2026-04-27 起草、しんごさんレビュー待ち） |
| 起草者 | 開発パートナー（Claude Code 経由） |
| 起草日 | 2026-04-27 |
| 関連ロードマップ | 仕様書 第8章 8-1（Phase 1-C: 商品マスタ、未着手、2-3日） |
| 関連未確定事項 | 仕様書 第8章 8-3「商品マスタ #24 の列構成と、在庫管理（SCM出力同期 #22・集計同期 #23）との関係整理」 |
| 関連 ADR | ADR-008 Supplier Intelligence（normalized_products / product_supplier_mappings の上位設計） |
| 関連設計書 | `jarvis_crm_system_overview.docx` 第5章 5-1、第6章 6-2/6-4/6-6、第8章 |
| 関連実装 | `backend/app/routers/products.py` (264行)、`backend/app/schemas/product.py`、`migrations/005_add_phase2_tenant_tables.sql` (L22-41)、`migrations/007_add_phase3_tenant_tables.sql` (suppliers, purchase_order_items.product_id FK)、`frontend/src/pages/ProductsPage.tsx` (250行) |
| 対象フェーズ | Phase 1-C（顧客マスタ・担当者マスタの後、Phase 2 ルックアップ群の前） |
| 対象テナント | tenant_004 (highlife-jpn) のみ（test-corp は空） |
| 本書のスコープ | **設計のみ**。実コード変更・migration 追加・commit/push なし。実装は別セッション。 |

---

## 0. TL;DR（先に結論）

- 既存 `products` テーブル（Phase 2 で migration 005 にて投入済、CRUD 完備、本番 tenant_004 で稼働中）は**そのまま温存**し、Phase 1-C は **段階的拡張（additive migration）** で実施する。
- 本設計の **核心は「決定版スキーマの確定」ではなく「決定版スキーマを確定するために何を聞くべきか」の整理**である。仕様書の Phase 1-C 記述は ロードマップ1行＋未確定事項1件のみで、実装に十分な情報を欠く。
- 結論として、本書は **設計を Q1〜Q9 のブロッカー解消後まで保留**し、実装着手は **しんごさんから #24 商品マスタ実物の列ヘッダー一覧（または列見本）の提供を受けた後**とする。Phase 1-B-2 (ADR 相当) と同じく「設計のみ・実装は別セッション」体制を取る。
- ただし、**しんごさんの確認待ちの間にも実装可能な「中間着地点 (M-MVP)」**を本書末尾に提示する：既存 products に「為替表示・廃番フラグ・画像 URL・JAN/型番」など TCG B2B 輸出で確実に必要な少数列を additive 追加し、`product_inventory` / `product_supplier_mappings` は ADR-008 (Supplier Intelligence) と統合して別フェーズに送る案。

---

## 1. 背景 / Context

### 1-1. 事業文脈

Treasure Island JP / HIGH LIFE JPN は、**トレーディングカードゲーム（TCG）の B2B 輸出事業者**である（仕様書 1章）。日本国内で仕入れた TCG 商品（ポケモンカード・遊戯王・MTG 等）を、海外のカード販売店・コレクター・卸売業者に輸出する。商品マスタ（products）は以下 4 業務すべての基盤となる：

1. **見積書作成**: `quotes` → `quote_items.product_id`（migration 005 L100）
2. **請求書作成**: `invoices` → `invoice_items.product_id`（migration 005 L147）
3. **仕入発注**: `purchase_orders` → `purchase_order_items.product_id`（migration 007 L50, NOT NULL FK）
4. **古物台帳（VIEW）**: `sales_orders + customers + products` から動的生成（仕様書 第6章 6-7、ADR-007 関連）

### 1-2. 既存実装の現状（2026-04-27 時点）

| レイヤー | 状況 |
|---|---|
| migration | `005_add_phase2_tenant_tables.sql` で `products` 13 列定義済（id, tenant_id, product_code, category, mark, name_en, name_ja, status, condition, unit_price, quantity, weight, notes, release_date, created_at, updated_at）。RLS 有効。`UNIQUE (tenant_id, product_code)` 等のユニーク制約は **未定義**。 |
| backend router | `backend/app/routers/products.py` 264行。`GET /products` (検索/ページング)、`GET /products/{id}`、`POST /products`（product_code は `PD-{id:05d}` 自動採番）、`PATCH /products/{id}`、`DELETE /products/{id}`、`GET /products/{id}/check-inventory`。`require_permission("products.view/create/update/delete")` 適用済み。audit_log 連動済。 |
| backend schema | `backend/app/schemas/product.py`。`ProductStatus = active | discontinued`（2値のみ）。 |
| frontend | `frontend/src/pages/ProductsPage.tsx` 250行。Create/Update/Delete フォーム + 検索 + 削除確認モーダル稼働中。 |
| 下流連携 | `quotes.py`, `invoices.py`, `purchase_orders.py` から `products.id` を FK 参照。`purchase_orders.py` の入荷確定時に `UPDATE products SET quantity = quantity + :qty`（migration 005 既存 quantity 列を在庫として流用）。 |

> **重要**: 既存 `products.quantity` 列は「**現在庫スナップショット**」として既に運用中。`purchase_orders` の `mark_received` で加算、出荷側（`sales_orders` 完了など）で減算が想定されるが、減算ロジックは現状 `orders.py` に未実装と思われる（要再確認）。本設計はこの既存運用を**壊さない**ことを前提とする。

### 1-3. 仕様書 Phase 1-C の記述量

仕様書から Phase 1-C 関連の記述を抽出した結果、以下のみ：

- 第6章 6-2 / 6-4 表: `products` = 「商品マスタ #24、未着手、依存 tenants」（1行）
- 第6章 6-4 表: `product_inventory` = 「SCM出力同期 #22 / 集計同期 #23、未着手、依存 products」（1行）
- 第6章 6-6 表: `normalized_products` / `product_supplier_mappings`（Supplier Intelligence 横断、ADR-008 で別建て）
- 第6章 6-7 依存関係図: `products ─ product_inventory`、`product_supplier_mappings ─ products`（線分のみ）
- 第8章 8-1 ロードマップ: 「Phase 1-C 商品マスタ（products）未着手 2-3日（設計＋実装）」（1行）
- 第8章 8-3 未確定事項: 「商品マスタ #24 の列構成と、在庫管理（SCM出力同期 #22・集計同期 #23）との関係整理」（1行）
- 第9章 9-2: 「migrate_products.md ※設計から未着手」（1行）

**つまり、仕様書には以下が記載されていない：**

- #24 商品マスタの列構成（何列あるか・どんな列か）
- #22 SCM出力同期 / #23 集計同期 と #24 の関係（同期方向、同期粒度、誰がマスタか）
- 在庫管理粒度（単一スナップショット / 倉庫別 / ロット別）
- TCG 商品コード命名規則（JAN・カードナンバー・拡張パック・レアリティ等）
- 商品画像の保管方針
- 多通貨価格保持の要否

### 1-4. 仕様書本文の重要訂正

ユーザー指示 (Mode B プロンプト) に「商品マスタの158列の意味（日別集計か商品別集計か）」とあるが、**仕様書 8-3 の「158列」は #2 売上管理（sales_orders）の列数であり、#24 商品マスタの列数ではない**（仕様書 7-? 第386行「売上管理（既存シート #2）は年次158列のワイドフォーマットで運用」、8-3「売上管理 #2 の158列の意味（日別集計なのか、商品別集計なのか）」）。

**よって本設計では「商品マスタの列数は不明（要しんごさん確認）」が正しい現状認識**である。158 列の話は Phase 3-C「売上管理・発送」設計で別途扱う。

---

## 2. ゴールと非ゴール

### 2-1. ゴール（G）

- **G1**: 既存 `products` テーブル・既存 `backend/app/routers/products.py`・既存 `frontend/src/pages/ProductsPage.tsx` を**破壊せず**、Phase 1-C で必要な追加列・追加副テーブルだけを additive に積み上げる。
- **G2**: 下流テーブル (`quote_items`, `invoice_items`, `purchase_order_items`) の `product_id` FK を**そのまま維持**する。本番 tenant_004 で既に稼働している商品レコード・関連ドキュメント（あれば）を破棄しない。
- **G3**: スプレッドシート #24 商品マスタの列構成をしんごさんから入手し、本書 §3 のスキーマ案に**マッピング表**として明記する。
- **G4**: 在庫管理（#22 SCM・#23 集計）は **product_inventory として別テーブル化**する。`products.quantity` は「最新スナップショット」として残し、履歴は副テーブルに切る（既存運用を壊さない移行戦略）。
- **G5**: Supplier Intelligence (ADR-008) との接合点 `product_supplier_mappings` の DB 定義は本書で**最低限の輪郭だけ確定**し、詳細仕様は ADR-008 に委譲する。
- **G6**: 多通貨対応（USD/EUR）と画像対応の方針を、本設計の段階で「採用 / 見送り / Phase 2 以降」のいずれか明示する。

### 2-2. 非ゴール（NG）

- **NG1**: スプレッドシート #2 売上管理（158列）のスキーマ化は本設計のスコープ外。Phase 3-C で別途扱う。
- **NG2**: Supplier Intelligence の AI 正規化フロー（supplier_raw_feeds → normalized_products）は ADR-008 で別建て。本書では `product_supplier_mappings` の **products 側 FK 外形**だけ示す。
- **NG3**: 古物台帳 VIEW（antique_ledger_snapshots）の本実装は Phase 4。本書では `products` がどの列を VIEW に提供するかだけ列挙する。
- **NG4**: 既存 `products.quantity` の意味再定義（在庫スナップショットから別の意味へ転用するなど）は行わない。`purchase_orders.py` の既存ロジックを壊さない。
- **NG5**: 多言語対応の本格展開（zh / ko など）は Phase 2 以降。本書では現状の `name_ja` / `name_en` 二言語に留める。
- **NG6**: Stripe 連携・決済通貨換算は ADR-010 で別建て。本書では「多通貨**保持**列の有無」だけ判断する。

---

## 3. 検討した代替案

### 案 A: products を全面再設計（破壊的マイグレーション）

`replace_customers_schema.sql` (migration 015) と同じ手法で、`products` を `_legacy_products` にリネームし新スキーマを CREATE → backfill する。

| 観点 | 評価 |
|---|---|
| #24 シート列の完全反映 | 高（自由設計） |
| 下流 FK 影響 | **大**（`quote_items.product_id`, `invoice_items.product_id`, `purchase_order_items.product_id` を再貼り直し） |
| 本番影響 | **大**（tenant_004 で稼働中、既存 quotes/invoices/purchase_orders レコードがあれば全件 FK 修正） |
| 工数 | 5-7日（顧客マスタ Phase 1-A と同等） |
| **採否** | **不採用**：仕様書 8-1 が「2-3日」と見積もる工数感と乖離。下流ドキュメント類に既存 product_id 参照があれば破壊リスク高。 |

### 案 B: 既存 products を additive 拡張のみ（最小着地）

既存 `products` テーブルにカラムを `ALTER TABLE ADD COLUMN` でのみ追加。副テーブル（`product_inventory`, `product_supplier_mappings`）は ADR-008 と Phase 2 に送る。

| 観点 | 評価 |
|---|---|
| 仕様書 8-3 の解消 | **不十分**（在庫履歴・SCM 同期・サプライヤー接続が宙に浮く） |
| 下流影響 | なし |
| 工数 | 0.5-1日 |
| **採否** | **不採用（単独では）**：8-3 の未確定事項を素通りする。ただし「中間着地 M-MVP」として本書 §10 に組み込み、Q1〜Q9 解消前の暫定実装として位置付ける。 |

### 案 C: 既存 products 温存 + 副テーブル切り出し【採用】

- `products` 本体: 既存 13 列を維持し、不足分（為替・廃番・画像 URL・TCG 命名規則関連）のみ additive に追加。
- `product_inventory`: 「在庫履歴 / 倉庫別在庫」を別テーブル化。`products.quantity` は「最新値スナップショット」として残置（既存 `purchase_orders.py` を壊さない）。
- `product_supplier_mappings`: 仕入先別マッピング（仕入価格・リードタイム）を別テーブル化。詳細は ADR-008 と整合。
- `product_pricing_history`: 価格改定履歴（任意、Phase 2 候補）。
- `product_images` / `product_attachments`: 画像・証明書（任意、Phase 2 候補）。

| 観点 | 評価 |
|---|---|
| #24 シート列の反映 | 中（本体に基本列、副テーブルに詳細） |
| 下流 FK 影響 | なし |
| 本番影響 | 小（ADD COLUMN は非破壊） |
| 工数 | 設計 1日 + 実装 2-3日（仕様書見積と整合） |
| 既存 routers.py への影響 | 段階的拡張（既存エンドポイントは無変更、新エンドポイントを追加） |
| **採否** | **採用** |

---

## 4. 採用案と理由

**案 C（既存 products 温存 + 副テーブル切り出し）** を採用する。理由：

1. **本番 tenant_004 を壊さない**: 既存 `products` レコードが tenant_004 にあるかは未確認だが、仮にあっても ADD COLUMN はゼロダウンタイム。
2. **仕様書 6章 DB マップとの整合**: 仕様書は `products ─ product_inventory` / `product_supplier_mappings ─ products` を依存図で示しており、副テーブル化は仕様書の意図と一致する。
3. **段階的着地が可能**: M-MVP（products 本体の追加列のみ）→ M-Inventory（product_inventory 追加）→ M-Supplier（product_supplier_mappings 追加、ADR-008 と同時）と、しんごさんからの #24 列情報の提供タイミングに合わせてフェーズ分割できる。
4. **下流影響ゼロ**: `quote_items.product_id` / `invoice_items.product_id` / `purchase_order_items.product_id` は無変更。

---

## 5. 提案スキーマ設計

> **注意**: 以下のカラムは **#24 商品マスタ実列が未確認のための仮設計**である。Q1〜Q5 解消後に確定する。

### 5-1. `products`（本体・既存テーブルへの追加列）

```sql
-- 既存（migration 005 で投入済）
-- id, tenant_id, product_code, category, mark, name_en, name_ja, status,
-- condition, unit_price, quantity, weight, notes, release_date, created_at, updated_at

-- 追加候補（Phase 1-C migration 038 で ADD COLUMN）
ALTER TABLE {schema}.products ADD COLUMN IF NOT EXISTS jan_code VARCHAR(20);             -- JAN/EAN（13桁）
ALTER TABLE {schema}.products ADD COLUMN IF NOT EXISTS card_number VARCHAR(50);          -- TCG カード番号（"SV1a-001/073" 等）
ALTER TABLE {schema}.products ADD COLUMN IF NOT EXISTS expansion_code VARCHAR(20);       -- 拡張パック略号
ALTER TABLE {schema}.products ADD COLUMN IF NOT EXISTS rarity VARCHAR(20);               -- レアリティ（C/U/R/SR/UR/SAR 等）
ALTER TABLE {schema}.products ADD COLUMN IF NOT EXISTS language VARCHAR(10);             -- 言語版（"ja" / "en" / "kr" 等）
ALTER TABLE {schema}.products ADD COLUMN IF NOT EXISTS unit_price_usd NUMERIC(15,2);     -- USD建て参考価格（多通貨保持）
ALTER TABLE {schema}.products ADD COLUMN IF NOT EXISTS unit_price_eur NUMERIC(15,2);     -- EUR建て参考価格
ALTER TABLE {schema}.products ADD COLUMN IF NOT EXISTS image_url VARCHAR(500);           -- 商品画像 URL（外部ストレージ）
ALTER TABLE {schema}.products ADD COLUMN IF NOT EXISTS is_archived BOOLEAN DEFAULT FALSE;-- 廃番論理削除フラグ（status='discontinued' とは別軸：non-display）
ALTER TABLE {schema}.products ADD COLUMN IF NOT EXISTS archived_at TIMESTAMPTZ;          -- 廃番日時
ALTER TABLE {schema}.products ADD COLUMN IF NOT EXISTS supplier_default_id INTEGER REFERENCES {schema}.suppliers(id); -- 既定仕入先（最頻仕入先）

-- 制約追加
CREATE UNIQUE INDEX IF NOT EXISTS uq_products_tenant_code
    ON {schema}.products (tenant_id, product_code) WHERE product_code IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS uq_products_tenant_jan
    ON {schema}.products (tenant_id, jan_code) WHERE jan_code IS NOT NULL;

-- 索引追加
CREATE INDEX IF NOT EXISTS idx_products_archived ON {schema}.products (is_archived);
CREATE INDEX IF NOT EXISTS idx_products_card_number ON {schema}.products (card_number) WHERE card_number IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_products_expansion ON {schema}.products (expansion_code) WHERE expansion_code IS NOT NULL;
```

**判断ポイント**:

- `jan_code` / `card_number` / `expansion_code` / `rarity` / `language` の 5 列は **TCG B2B 輸出で確実に必要**（型番検索・国際取引で版数指定）と判断し、Q4 で確認しつつ採用前提。
- `unit_price_usd` / `unit_price_eur` は **海外顧客との見積で頻出**するため、JPY 単一価格＋為替換算ではなく**多通貨保持** (denormalize) を提案。リアルタイム為替は別途 `exchange_rates` テーブル（Phase 2）で扱う。
- `is_archived` は `status='discontinued'` と別軸（非表示と廃番の区別。`discontinued` は仕入終了だが在庫ある、`is_archived=true` は UI 表示から除外する）。
- `supplier_default_id` は「最頻仕入先 1 件」の高速参照用 denormalize。詳細は `product_supplier_mappings`（多対多）に。

### 5-2. `product_inventory`（在庫履歴 / 倉庫別在庫）

```sql
CREATE TABLE IF NOT EXISTS {schema}.product_inventory (
    id BIGSERIAL PRIMARY KEY,
    tenant_id INTEGER NOT NULL DEFAULT {tenant_id},
    product_id INTEGER NOT NULL REFERENCES {schema}.products(id) ON DELETE RESTRICT,
    warehouse_code VARCHAR(20) NOT NULL DEFAULT 'main',  -- 倉庫識別（main / consignment / supplier_X 等）
    quantity_delta INTEGER NOT NULL,                     -- 増減（仕入+、売上-、棚卸調整±）
    reason VARCHAR(50) NOT NULL,                         -- purchase_received / sales_shipped / stocktake / manual
    reference_type VARCHAR(50),                          -- "purchase_orders" / "sales_orders" / "stocktake"
    reference_id INTEGER,                                -- 紐づく purchase_orders.id 等
    quantity_after INTEGER NOT NULL,                     -- 適用後の在庫スナップショット
    notes TEXT,
    created_by INTEGER REFERENCES {schema}.staff(id),
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_product_inventory_product ON {schema}.product_inventory (product_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_product_inventory_ref ON {schema}.product_inventory (reference_type, reference_id);

ALTER TABLE {schema}.product_inventory ENABLE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation_product_inventory ON {schema}.product_inventory
    USING (tenant_id = current_setting('app.tenant_id', true)::INTEGER);
```

**判断ポイント**:

- **イベントソーシング型**（増減ログ + スナップショット）を採用。`products.quantity` は「最新スナップショット」として温存し、`product_inventory.quantity_after` の最新値とトリガー or アプリで同期する。
- 倉庫粒度は `warehouse_code VARCHAR` で柔軟化（Q3 で確認）。HIGH LIFE JPN は当面 `main` 一拠点想定だが、委託在庫やサプライヤー預り在庫が出た場合に拡張可能。
- ロット・シリアル粒度は **本設計のスコープ外**（TCG カードでロット管理は通常不要、Q3 で確認）。
- 既存 `purchase_orders.py` の `mark_received` は、トランザクション内で `products.quantity += qty` と `product_inventory INSERT` を両方行うよう拡張する。

### 5-3. `product_supplier_mappings`（仕入先別マッピング）

```sql
CREATE TABLE IF NOT EXISTS {schema}.product_supplier_mappings (
    id SERIAL PRIMARY KEY,
    tenant_id INTEGER NOT NULL DEFAULT {tenant_id},
    product_id INTEGER NOT NULL REFERENCES {schema}.products(id) ON DELETE CASCADE,
    supplier_id INTEGER NOT NULL REFERENCES {schema}.suppliers(id) ON DELETE RESTRICT,
    supplier_sku VARCHAR(100),                           -- 仕入先側の品番
    cost_price NUMERIC(15,2),                            -- 仕入価格（最新）
    cost_currency VARCHAR(10) DEFAULT 'JPY',
    lead_time_days INTEGER,                              -- リードタイム（営業日）
    minimum_order_quantity INTEGER DEFAULT 1,
    is_primary BOOLEAN DEFAULT FALSE,                    -- 主仕入先フラグ
    last_purchased_at TIMESTAMPTZ,
    notes TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (tenant_id, product_id, supplier_id)
);

CREATE INDEX IF NOT EXISTS idx_psm_product ON {schema}.product_supplier_mappings (product_id);
CREATE INDEX IF NOT EXISTS idx_psm_supplier ON {schema}.product_supplier_mappings (supplier_id);

ALTER TABLE {schema}.product_supplier_mappings ENABLE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation_psm ON {schema}.product_supplier_mappings
    USING (tenant_id = current_setting('app.tenant_id', true)::INTEGER);
```

**判断ポイント**:

- 多対多（1商品が複数サプライヤー、1サプライヤーが複数商品）。
- `is_primary` で主仕入先 1 件を識別し、`products.supplier_default_id` と整合させる（トリガー or アプリ層で）。
- ADR-008 (Supplier Intelligence) の `normalized_products` との接合点：**normalized_products は供給側、product_supplier_mappings は需要側のミラー**。AI 正規化結果を採用するときに `product_supplier_mappings` に書き込む（詳細は ADR-008）。

### 5-4. `product_pricing_history`（任意・Phase 2 候補）

価格改定履歴。`unit_price` / `unit_price_usd` の変更を時系列で残す。BtoB レート交渉・古物台帳の取得時単価記録に使う。

```sql
-- スコープ外宣言（Phase 2 で再検討）
-- columns: product_id, currency, old_price, new_price, changed_by, changed_at, reason
```

### 5-5. `product_images` / `product_attachments`（任意・Phase 2 候補）

商品画像・証明書（古物商法対応の取得時写真）。**Q5（保管場所）が未確定のため設計凍結**。`products.image_url` 単一列で当面回す。

```sql
-- スコープ外宣言（Q5 解消後に Phase 2 で再検討）
-- columns: product_id, kind (image/certificate/manual), url, mime_type, file_size, sort_order, uploaded_by, uploaded_at
```

---

## 6. 下流テーブルとの関係

| 下流テーブル | 既存 FK | 本設計での影響 |
|---|---|---|
| `quote_items.product_id` | `REFERENCES products(id)` (migration 005 L100, NULL 許可) | 影響なし |
| `invoice_items.product_id` | `REFERENCES products(id)` (migration 005 L147, NULL 許可) | 影響なし |
| `purchase_order_items.product_id` | `REFERENCES products(id)` (migration 007 L50, NOT NULL) | 影響なし。受領時の在庫更新は `products.quantity` 更新 + `product_inventory` INSERT に拡張。 |
| `sales_orders` / `sales_order_items` | 仕様書では予定（migration 未投入） | Phase 3-C で投入時、`product_id` を `REFERENCES products(id)` で貼る前提。 |
| `antique_ledger` (VIEW) | 仕様書 6-7、Phase 4 | `products` から取得するのは: id, name_ja, product_code, condition, release_date 等。本設計の追加列は VIEW に**追加しない**（古物法定帳簿は最小列で固定）。 |

---

## 7. マイグレーション計画（暫定）

### 7-1. 投入順（Phase 1-C 内）

| # | migration | 内容 | 工数 |
|---|---|---|---|
| 038 | `add_products_phase1c_columns.sql` | products に 11 列 ADD COLUMN + UNIQUE INDEX 2 本 + 索引 3 本 | 0.5d |
| 039 | `create_product_inventory.sql` | product_inventory CREATE + RLS + 索引 | 0.5d |
| 040 | `create_product_supplier_mappings.sql` | product_supplier_mappings CREATE + RLS + 索引 | 0.5d |
| 041 | `backfill_products_supplier_default.sql` | 既存 `purchase_order_items` 履歴から最頻仕入先を集計し `products.supplier_default_id` を埋める | 0.5d |
| 042 | `backfill_product_inventory_initial.sql` | 各 product の現在 `quantity` を「初期スナップショット」として `product_inventory` に 1 行 INSERT（reason='initial_backfill'） | 0.5d |

### 7-2. 既存データ保全

- 本番 tenant_004 の products レコード件数を **migration 着手前に必ず確認**（`SELECT COUNT(*) FROM products WHERE tenant_id = 4`）。
- 件数 0 件の場合は 041 / 042 backfill 不要。件数 ≥ 1 件の場合は backfill 必須。
- ADD COLUMN はゼロダウンタイム、RLS POLICY 追加もゼロダウンタイム（既存 SELECT に影響なし）。

### 7-3. ロールバック戦略

- migration 038-040 は `DROP COLUMN` / `DROP TABLE` で完全ロールバック可能。
- migration 041-042 は backfill のみで構造変更なし。ロールバックは `UPDATE products SET supplier_default_id = NULL` / `DELETE FROM product_inventory WHERE reason = 'initial_backfill'` で対応。

---

## 8. API 拡張計画

### 8-1. 既存 endpoint の拡張（無変更を優先）

| endpoint | 現状 | 本設計後 |
|---|---|---|
| `GET /products` | 検索/ページング | レスポンスに新規 11 列を追加。クエリパラメータに `?expansion=`, `?rarity=`, `?archived=false` を追加（任意）。 |
| `GET /products/{id}` | 単一取得 | 同上 |
| `POST /products` | 作成 | 新規 11 列を受け付け。`product_code` 自動採番（`PD-{id:05d}`）は維持。`UNIQUE(tenant_id, jan_code)` 違反を 409 で返す。 |
| `PATCH /products/{id}` | 更新 | 新規 11 列を更新可能カラムに追加。 |
| `DELETE /products/{id}` | 物理削除 | **本設計で見直し**: 下流 `quote_items` / `invoice_items` で参照中の場合は 409 で拒否。代わりに `is_archived = true` を勧める。 |
| `GET /products/{id}/check-inventory` | 在庫チェック | 維持（既存 `products.quantity` を読む）。 |

### 8-2. 新規 endpoint

| endpoint | 用途 | 権限 |
|---|---|---|
| `POST /products/{id}/archive` | `is_archived = true`、`archived_at = NOW()` | `products.update` |
| `POST /products/{id}/unarchive` | `is_archived = false`、`archived_at = NULL` | `products.update` |
| `GET /products/{id}/inventory-history` | `product_inventory` の時系列 | `products.view` |
| `POST /products/{id}/inventory-adjust` | 棚卸調整。`quantity_delta` を受けて `product_inventory` INSERT + `products.quantity` 更新 | 新規 `inventory.adjust` 権限（または既存 `products.update`） |
| `GET /products/{id}/suppliers` | `product_supplier_mappings` 一覧 | `products.view` |
| `POST /products/{id}/suppliers` | mapping 追加 | `products.update`（または `suppliers.update`） |
| `PATCH /products/{id}/suppliers/{mapping_id}` | mapping 更新 | 同上 |
| `DELETE /products/{id}/suppliers/{mapping_id}` | mapping 削除 | 同上 |

### 8-3. Pydantic schema 更新

`backend/app/schemas/product.py` に以下を追加：

- `ProductCreate` / `ProductUpdate` / `ProductResponse` に新規 11 列を追加。
- 新規 `InventoryHistoryResponse`, `InventoryAdjustRequest`, `ProductSupplierMappingCreate/Update/Response`。
- `ProductStatus` enum に **`archived` を追加するかは見送り**（is_archived は別軸フラグのため、status は active/discontinued の 2 値のまま）。

### 8-4. 権限の追加

migration 042 等で `permissions` マスタに以下を追加（仕様書 §3-2 の権限テーブル準拠）：

- `inventory.view` / `inventory.adjust`（在庫履歴・棚卸権限）
- `products.archive`（既存 products.update に統合可、Q9）

---

## 9. Frontend 拡張計画

### 9-1. 既存 `ProductsPage.tsx` の拡張

- 一覧テーブルに「JAN」「カード番号」「拡張」「レア」「USD価格」列を追加（横スクロール想定）。
- フォームに新規 11 列の入力欄を追加（タブ分割推奨：基本情報 / TCG属性 / 価格 / 在庫 / その他）。
- `is_archived = true` の商品はデフォルトで非表示、トグルで表示切替。
- 削除ボタンは「アーカイブ」と「物理削除（FK 参照なし時のみ）」の二段。

### 9-2. 新規ページ・タブ

- `ProductDetailPage.tsx`（新規）: 商品詳細 + 在庫履歴タブ + 仕入先マッピングタブ。
  - 既存 `ProductsPage.tsx` の編集モーダルでは情報量が増えすぎるため、CompanyDetailPage のような専用ページ化を推奨。
- 在庫管理画面: `ProductDetailPage` 内タブで完結（独立ページ不要）。

### 9-3. 着手判断

- **M-MVP では既存 `ProductsPage.tsx` の最小拡張のみ**（新規列の表示・編集）。
- `ProductDetailPage` 新設は Phase 1-C 後半（在庫履歴・仕入先マッピングが migration 投入された後）。

---

## 10. 中間着地点（M-MVP）— Q1〜Q9 解消前の暫定実装

しんごさんからの #24 列情報の提供を待つ間、以下の **限定スコープ M-MVP** を先行実装可能：

### M-MVP のスコープ（実装着手判断 = "GO" の場合）

- migration 038 のみ実行（products に新規 11 列を ADD COLUMN）。
- 副テーブル (`product_inventory`, `product_supplier_mappings`) は**保留**（Q3 / Q6 解消後）。
- backend/router: 既存 endpoint のレスポンス拡張のみ。新規 endpoint は追加しない。
- frontend: 既存 `ProductsPage.tsx` のフォームと一覧に新規 11 列を追加。`ProductDetailPage` は作らない。
- 工数見積: **0.5-1日**（仕様書 8-1 の「2-3日」枠の前半に収まる）。

### M-MVP の制約

- 在庫履歴は取れない（`products.quantity` 単一スナップショットのまま）。
- 仕入先マッピングは取れない（`products.supplier_default_id` の単一参照のみ）。
- 多通貨価格は持てるが、表示通貨のロジックは frontend に寄せる（為替テーブルなし）。

### M-MVP 後の継続パス

| マイルストーン | 含む範囲 | 前提 |
|---|---|---|
| **M1（現在）**: 設計レビュー | 本書承認 + Q1〜Q9 回答 | しんごさん確認 |
| **M2: M-MVP 実装** | migration 038 + 既存 router/page 拡張 | M1 完了 + Q4/Q5/Q9 のみ最低限解消 |
| **M3: product_inventory 投入** | migration 039, 042 + inventory endpoint + ProductDetailPage 新設 | Q3（在庫粒度・倉庫粒度・SCM 同期方向）解消 |
| **M4: product_supplier_mappings 投入** | migration 040, 041 + supplier 関連 endpoint | Q6（ADR-008 との切り分け）解消 |
| **M5: 価格履歴・画像副テーブル** | Phase 2 送り | Q5 / Q7 解消 |

工数合計目安: **M2: 1日、M3: 1.5日、M4: 1日、M5: Phase 2**。仕様書見積「2-3日（設計＋実装）」は M-MVP + M3 までを想定したものと推定。

---

## 11. しんごさんへの未確定事項リスト（Q1〜Q9）

| # | 質問 | ブロックする M | 想定回答パターン |
|---|---|---|---|
| **Q1** | スプレッドシート #24「商品マスタ」の **列ヘッダー一覧（または列見本 1 行）** を共有可能か？ 列数も知りたい。 | M1 完了の前提 | 共有可（M2 着手）/ 列がない・運用していない（既存設計で確定）/ 後日（M-MVP 先行） |
| **Q2** | 仕様書 8-3「158 列」は #2 売上管理の話と理解しているが、**#24 商品マスタの列数の認識**は？ | M1 | おおむね 5〜30 列想定 / 100 列超 / 不明 |
| **Q3** | 在庫管理粒度: (a) 単一拠点・単一スナップショット (b) 複数倉庫 (c) ロット/シリアル管理 のどれ？ #22 SCM出力同期 / #23 集計同期 とは何の同期で、どちらがマスタ？ | M3 | (a) HIGH LIFE JPN は単一倉庫 / (b) 委託在庫あり / (c) ロット必要 |
| **Q4** | TCG 商品コード命名規則は社内で固まっている？ 既存 `PD-{id:05d}` 自動採番で十分か、JAN・カード番号・拡張パック略号が必要か？ | M-MVP 着手 | 自動採番で OK（既存通り）/ JAN 必要 / カード番号必要（推奨） |
| **Q5** | 商品画像の保管場所は？ (a) 外部 URL のみ (b) S3/Cloudflare R2 等のストレージ (c) DB に base64 (d) ファイル添付なし | M-MVP / Phase 2 | (a) URL で OK / (b) ストレージ前提（別 ADR 必要）/ (d) 不要 |
| **Q6** | Supplier Intelligence (ADR-008) と `product_supplier_mappings` の **責務境界**は？ ADR-008 の `normalized_products` から `products` への昇格時に `product_supplier_mappings` を自動生成するか、それとも手動マッピングか？ | M4 | 自動生成 / 半自動（AI 提案 → 人間承認）/ 手動のみ |
| **Q7** | 多通貨価格保持: USD / EUR をテーブル列で持つか、為替レートテーブルから都度換算するか？ | M-MVP | 列で持つ（提案）/ 為替換算（Phase 2）/ JPY のみ（多通貨不要） |
| **Q8** | 廃番商品の扱い: `status='discontinued'` と `is_archived` を分けるか統合するか？ 古物台帳に廃番商品も載るか？ | M-MVP | 分ける（提案）/ 統合 / 古物台帳は廃番含む |
| **Q9** | 物理削除 vs 論理削除: 既存 `DELETE /products/{id}` は物理削除だが、下流参照あり時は 409 拒否＋アーカイブ推奨に変更してよいか？ | M-MVP | OK（提案通り）/ 物理削除維持 |

---

## 12. 想定リスク

| # | リスク | 影響 | 緩和策 |
|---|---|---|---|
| R1 | 本番 tenant_004 の `products` レコードが既に多数あり、追加列の backfill が必要だが NULL 値を補完するデフォルト値が決まらない | 既存データ品質低下 | migration 038 は全列 NULL 許可で投入。手動 backfill は別タスク化。 |
| R2 | `purchase_orders.py` の在庫加算ロジックを `product_inventory` 連動に拡張する際、既存トランザクションを壊す | 仕入受領処理の停止 | M3 で実装、テスト環境で先行検証、`product_inventory` への INSERT 失敗を rollback トリガーに。 |
| R3 | `products.is_archived` 追加で frontend が「廃番除外」を忘れて廃番商品が見積に乗る | 営業ミス | 既存 `GET /products` のデフォルトを `?archived=false` に。明示的に `?archived=true` を渡したときだけ含める。 |
| R4 | `UNIQUE(tenant_id, jan_code)` 制約追加時、既存データに JAN 重複があれば migration 失敗 | デプロイ停止 | UNIQUE は **PARTIAL INDEX (WHERE jan_code IS NOT NULL)** で投入。重複検出は migration 前に SELECT で事前確認。 |
| R5 | ADR-008 (Supplier Intelligence) の設計が `product_supplier_mappings` のスキーマに後から修正を要求する | M4 の手戻り | M4 着手前に ADR-008 を起草（または並行）し、本書 §5-3 と整合確認。 |
| R6 | `quote_items.product_id` / `invoice_items.product_id` が NULL（手入力商品）レコードがあり、`products.id` 経由のレポートが欠損 | 集計の不整合 | 仕様書 6章既定の通り NULL 許可は維持。レポート側で NULL を「unmapped」として扱う方針を別途決定。 |
| R7 | 商品画像（Q5）を S3 等に置く設計が確定しないまま M-MVP の `image_url` 単一列で運用開始 → 後で複数画像対応に変更が必要 | スキーマ再設計 | M-MVP では `image_url VARCHAR(500)` の **単一列**に留め、複数画像化は `product_images` 副テーブルで Phase 2 に。 |

---

## 13. 着手判断（しんごさんへの提案）

### 推奨: **設計レビュー → Q4/Q5/Q9 のみ即答 → M-MVP 先行実装**

以下の二段構え：

#### Step 1（即時）: 本書のレビューと Q4 / Q5 / Q9 の回答

- Q4（TCG 命名規則）: 提案（カード番号＋拡張パック＋レアリティ列追加）を OK / NG。
- Q5（画像保管）: 提案（image_url 単一列、ストレージは Phase 2）を OK / NG。
- Q9（削除挙動）: 提案（FK 参照あり時は 409、is_archived 推奨）を OK / NG。

→ Q4/Q5/Q9 が OK ならば **M2（M-MVP 実装）に即着手可能**。

#### Step 2（M2 完了後）: Q1 / Q3 / Q6 の解消 → M3 / M4 着手

- Q1（#24 列ヘッダー）: しんごさんから列見本を共有してもらう。
- Q3（在庫粒度・SCM 同期）: ヒアリング会議で確定。
- Q6（ADR-008 との切り分け）: ADR-008 起草と同時並行。

### ブロックされる場合の扱い

- Q4 / Q5 / Q9 のいずれかで「方針未定」になる場合、M-MVP も着手不可。**設計のみで打ち切り、M2 着手は別セッション**とする。Phase 1-B-2（ADR 相当）と同じパターン。
- Q1 が「列がない・運用していない」回答ならば、本書の §5-1 提案列のうち TCG 関連列は仕様書 1章の TCG 事業文脈から確実性が高いため、Q4 のみで M-MVP 着手可能。

---

## 14. 次のアクション

### 開発パートナー側

1. しんごさんに本書を共有し、§11 Q1〜Q9 への回答を依頼。
2. しんごさんからの #24 列ヘッダーが共有された場合、本書 §5-1 のスキーマ案と **マッピング表**を §5-1 に追記し、本書を v1.1 として更新。
3. M2 着手判断後、別セッションで `migrate_products.md`（Claude Code 用実装指示書、第9章 9-2 リスト準拠）を起草。

### しんごさん側

1. 本書 §11 Q1〜Q9 のうち、**Q4 / Q5 / Q9 を最優先で回答**（M-MVP 着手判断のため）。
2. スプレッドシート #24「商品マスタ」の列ヘッダー（1 行目）を CSV か画像で共有（Q1）。
3. #22 SCM出力同期 / #23 集計同期の運用実態（誰がいつ何を同期しているか）を 5 分程度で説明（Q3）。
4. ADR-008 (Supplier Intelligence) の起草優先度を確定（Q6 解消の前提）。

---

## 付録 A: 参照 ID 一覧（仕様書連携）

| 仕様書スプレッドシート ID | 名称 | 本設計での扱い |
|---|---|---|
| #2 | 売上管理（158列） | 本設計対象外（Phase 3-C） |
| #22 | SCM 出力同期 | `product_inventory` への入力源として位置付け（Q3 解消後確定） |
| #23 | 集計同期 | 同上 |
| #24 | 商品マスタ | 本設計の主対象（Q1 解消後にスキーママッピング確定） |

## 付録 B: 既存実装ファイル一覧（変更影響範囲）

- 影響: `backend/app/routers/products.py` (264行) — 新規列対応で行数増（推定 +150 行）
- 影響: `backend/app/schemas/product.py` (76行) — 新規 schema 追加で行数増（推定 +120 行）
- 影響: `frontend/src/pages/ProductsPage.tsx` (250行) — 列追加・フォーム拡張で行数増（推定 +100 行）
- 新規: `frontend/src/pages/ProductDetailPage.tsx` (M3 で新設、推定 300 行)
- 新規: `migrations/038_add_products_phase1c_columns.sql`
- 新規: `migrations/039_create_product_inventory.sql`
- 新規: `migrations/040_create_product_supplier_mappings.sql`
- 新規: `migrations/041_backfill_products_supplier_default.sql`
- 新規: `migrations/042_backfill_product_inventory_initial.sql`
- 関連 (無変更前提): `backend/app/routers/quotes.py` / `invoices.py` / `purchase_orders.py` — `product_id` FK 参照は既存通り

---

以上 / End of Document
Treasure Island JP / HIGH LIFE JPN — Phase 1-C 商品マスタ再設計 v1.0 (Proposed) — 2026-04-27
