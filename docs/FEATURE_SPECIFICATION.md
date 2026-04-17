# Jarvis CRM 機能仕様書

> 旧システム（Google Apps Script版）の全機能を棚卸しし、新システム（FastAPI + React）への移植計画を定義する。

## 変更履歴

| 日付 | 変更内容 |
|------|---------|
| 2026-04-17 | Phase 3 全完了: 仕入れ管理（2.8）、重複検知（2.23）、ダッシュボード拡張（2.12）、レポート・分析拡張（2.13）を実装 |
| 2026-04-17 | Phase 2 実装完了: 在庫管理（2.7）、見積もり管理（2.4）、請求書管理（2.5）、注文拡張（2.6）、配送管理（2.9）を実装 |
| 2026-04-16 | Phase 1 実装完了: ロール・権限（2.14）、顧客拡張（2.1）、リード管理（2.2）、案件拡張（2.3）、チーム管理（2.15）を実装 |
| 2026-04-16 | 初版作成（旧GASシステムの機能棚卸し） |

---

## 1. 現状比較サマリー

### 凡例

| 記号 | 意味 |
|------|------|
| :white_check_mark: | 実装済み |
| :construction: | 一部実装 |
| :x: | 未実装（移植必要） |
| :no_entry_sign: | 廃止（移植不要） |

### 機能対照表

| # | 機能領域 | 旧GAS | 新Jarvis | 状態 |
|---|----------|-------|----------|------|
| 1 | 顧客マスタ管理 | :white_check_mark: | :white_check_mark: | **Phase 1完了**（請求先/配送先/顧客コード追加） |
| 2 | リード管理 | :white_check_mark: | :white_check_mark: | **Phase 1完了**（見込度自動算出・案件化含む） |
| 3 | 案件（Deal）管理 | :white_check_mark: | :white_check_mark: | **Phase 1完了**（deal_code/stage/probability/currency追加） |
| 4 | 見積もり管理 | :white_check_mark: | :white_check_mark: | **Phase 2完了**（明細管理・ステータス遷移・請求書変換） |
| 5 | 請求書管理 | :white_check_mark: | :white_check_mark: | **Phase 2完了**（多通貨・void・枝番・ERP Key） |
| 6 | 注文管理 | :white_check_mark: | :white_check_mark: | **Phase 2完了**（配送情報・ステータス拡張） |
| 7 | 在庫管理 | :white_check_mark: | :white_check_mark: | **Phase 2完了**（商品マスタ・在庫チェック） |
| 8 | 仕入れ・調達管理 | :white_check_mark: | :white_check_mark: | **Phase 3完了**（仕入先CRUD・PO・入荷→在庫自動加算） |
| 9 | 配送・物流管理 | :white_check_mark: | :white_check_mark: | **Phase 2完了**（ゾーン/料金マスタ・3社比較自動計算） |
| 10 | ERP連携 | :white_check_mark: | :x: | **未実装** |
| 11 | 見込み客ランク（自動算出） | :white_check_mark: | :x: | **未実装** |
| 12 | ダッシュボード・KPI | :white_check_mark: | :white_check_mark: | **Phase 3完了**（パイプライン/コンバージョン/未入金/在庫金額/仕入） |
| 13 | レポート・分析 | :white_check_mark: | :white_check_mark: | **Phase 3完了**（コンバージョン分析/案件停滞/未入金一覧/CSVエクスポート） |
| 14 | ロール・権限管理 | :white_check_mark: | :white_check_mark: | **Phase 1完了**（Discord式カスタムロール） |
| 15 | チーム管理 | :white_check_mark: | :white_check_mark: | **Phase 1完了**（チームCRUD＋メンバー管理） |
| 16 | シフト管理 | :white_check_mark: | :x: | **未実装** |
| 17 | Meta連携（WhatsApp/Instagram） | :white_check_mark: | :x: | **未実装** |
| 18 | Discord通知 | :white_check_mark: | :x: | **未実装** |
| 19 | 日報・週報・月報 | :white_check_mark: | :x: | **未実装** |
| 20 | Buddy/コーチングシステム | :white_check_mark: | :x: | **未実装** |
| 21 | バッジ・ゲーミフィケーション | :white_check_mark: | :x: | **未実装** |
| 22 | リマインダー・通知 | :white_check_mark: | :x: | **未実装** |
| 23 | 重複検知 | :white_check_mark: | :white_check_mark: | **Phase 3完了**（メール/電話/会社名+名前の重複検出・マージ） |
| 24 | アーカイブ・復元 | :white_check_mark: | :x: | **未実装** |
| 25 | 監査ログ | :white_check_mark: | :white_check_mark: | 実装済み |
| 26 | マルチテナント | :no_entry_sign: | :white_check_mark: | 新規（GASになし） |
| 27 | Firebase MFA認証 | :no_entry_sign: | :white_check_mark: | 新規（GASになし） |

---

## 2. 機能仕様詳細

---

### 2.1 顧客マスタ管理

**概要**: B2B顧客の基本情報・請求先・配送先を一元管理する。

#### 現行の実装状態
- 基本CRUD実装済み（name, email, phone, company, notes）

#### 旧システムから移植すべき項目

| フィールド | 型 | 説明 | 必須 |
|-----------|-----|------|------|
| customer_code | string | 顧客コード（CT-XXXXX自動採番） | Yes（自動） |
| registration_source | string | 登録元（Inbound/Outbound/紹介等） | No |
| billing_name | string | 請求先名 | No |
| billing_phone | string | 請求先電話番号 | No |
| billing_email | string | 請求先メール | No |
| billing_address | text | 請求先住所 | No |
| delivery_name | string | 配送先名 | No |
| delivery_phone | string | 配送先電話番号 | No |
| delivery_email | string | 配送先メール | No |
| delivery_address | text | 配送先住所 | No |
| delivery_country | string | 配送先国（配送料計算に使用） | No |
| business_id | string | 法人番号/事業者ID | No |
| status | enum | Active / Inactive | Yes |
| transaction_count | integer | 取引回数（自動集計） | 自動 |
| last_transaction_date | datetime | 最終取引日（自動更新） | 自動 |

#### ビジネスルール
- 請求先が未入力の場合、基本情報から自動コピー
- 配送先は請求先と異なる住所を設定可能
- 削除はソフトデリート（status=Inactiveに変更）
- 関連する案件・注文がある顧客は物理削除不可（既存実装を維持）

---

### 2.2 リード管理

**概要**: 見込み客を獲得段階から管理し、案件化までのパイプラインを追跡する。

#### データモデル

| フィールド | 型 | 説明 | 必須 |
|-----------|-----|------|------|
| id | integer | PK | 自動 |
| tenant_id | integer | FK→tenants | 自動 |
| lead_code | string | リードコード（LD-XXXXX自動採番） | 自動 |
| customer_name | string | 見込み客名 | Yes |
| company_name | string | 会社名 | No |
| email | string | メールアドレス | No |
| phone | string | 電話番号 | No |
| source | enum | 流入元 | Yes |
| type | enum | Inbound / Outbound | Yes |
| status | enum | リードステータス | Yes |
| temperature | enum | 温度感（Hot/Warm/Cold） | No |
| estimated_scale | enum | 想定規模（Small/Medium/Large） | No |
| customer_type | enum | 顧客タイプ（信頼重視/価格重視） | No |
| response_speed | enum | 返信速度（24h以内/3日以内/3日超） | No |
| monthly_forecast | decimal | 月間見込み金額 | No |
| prospect_rank | enum | 見込度ランク（自動算出） | 自動 |
| assigned_to | integer | FK→users（担当者） | No |
| notes | text | 備考 | No |
| converted_deal_id | integer | FK→deals（案件化時にリンク） | No |
| created_at | datetime | 作成日 | 自動 |
| updated_at | datetime | 更新日 | 自動 |

#### ステータス遷移
```
新規 → コンタクト中 → 提案中 → 案件化（→Dealへ変換）
                                 → 失注
                                 → 保留
```

#### 流入元（source）選択肢
- Web問い合わせ、展示会、紹介、SNS、電話、メール、その他

#### ビジネスルール
- 「案件化」時にDealレコードを自動生成し、`converted_deal_id`をリンク
- 見込度ランク（prospect_rank）は温度感・想定規模等から自動算出（§2.11参照）
- 担当者アサインはチーム・個人の負荷状況を考慮（§2.15参照）

---

### 2.3 案件（Deal）管理

**概要**: 商談の進捗・金額・成約見込みを管理する。

#### 現行の実装状態
- 基本CRUD実装済み（customer_id, title, amount, status, expected_close_date, notes）

#### 旧システムから移植すべき項目

| フィールド | 型 | 説明 | 必須 |
|-----------|-----|------|------|
| deal_code | string | 案件コード（DL-XXXXX自動採番） | 自動 |
| lead_id | integer | FK→leads（リードからの変換元） | No |
| assigned_to | integer | FK→users（担当者） | No |
| stage | enum | 案件ステージ（詳細パイプライン） | Yes |
| probability | integer | 成約確率（%）※ステージ連動 | 自動 |
| lost_reason | string | 失注理由（status=lost時） | No |
| currency | enum | 通貨（JPY/USD/EUR） | Yes |

#### ステータス拡張
```
open → negotiating → proposal → won / lost / on_hold
```

#### ステージと成約確率の連動
| ステージ | 成約確率 |
|---------|---------|
| open（初回接触） | 10% |
| negotiating（ヒアリング中） | 30% |
| proposal（見積提出済み） | 60% |
| won（成約） | 100% |
| lost（失注） | 0% |
| on_hold（保留） | — |

---

### 2.4 見積もり管理

**概要**: 案件に紐づく見積書を作成・管理し、承認後に請求書へ変換する。

#### データモデル — 見積ヘッダー（quotes）

| フィールド | 型 | 説明 | 必須 |
|-----------|-----|------|------|
| id | integer | PK | 自動 |
| tenant_id | integer | FK→tenants | 自動 |
| quote_code | string | 見積番号（QT-XXXXX自動採番） | 自動 |
| deal_id | integer | FK→deals | Yes |
| customer_id | integer | FK→customers | Yes |
| currency | enum | JPY / USD / EUR | Yes |
| subtotal | decimal(15,2) | 小計 | 自動計算 |
| shipping_fee | decimal(15,2) | 送料 | No |
| tax_amount | decimal(15,2) | 税額 | No |
| total_amount | decimal(15,2) | 合計 | 自動計算 |
| status | enum | ステータス | Yes |
| validity_date | date | 有効期限（作成日+30日） | 自動 |
| delivery_info | text | 配送先情報 | No |
| notes | text | 備考 | No |
| pdf_url | string | 生成PDF URL | No |
| created_by | integer | FK→users（作成者） | 自動 |
| invoice_id | integer | FK→invoices（請求書変換後リンク） | No |
| created_at | datetime | | 自動 |
| updated_at | datetime | | 自動 |

#### データモデル — 見積明細（quote_items）

| フィールド | 型 | 説明 | 必須 |
|-----------|-----|------|------|
| id | integer | PK | 自動 |
| quote_id | integer | FK→quotes | Yes |
| product_name | string | 商品名 | Yes |
| quantity | integer | 数量 | Yes |
| unit_price | decimal(15,2) | 単価 | Yes |
| weight | decimal(10,3) | 重量（kg） | No |
| subtotal | decimal(15,2) | 行小計 | 自動計算 |

#### ステータス遷移
```
Draft → Sent → Approved → (請求書変換)
                → Rejected
         → Expired（有効期限超過時に自動遷移）
```

#### ビジネスルール
- Approved/Rejected状態の見積もりは編集不可
- Approved見積もりのみ請求書変換（convertQuoteToInvoice）が可能
- 有効期限（validity_date）超過分は日次バッチでExpiredに自動更新
- 送料は配送先国＋重量から自動見積もり可能（§2.9参照）

---

### 2.5 請求書管理

**概要**: 見積もりの承認後に請求書を発行し、PDF生成・入金管理を行う。

#### データモデル — 請求書ヘッダー（invoices）

| フィールド | 型 | 説明 | 必須 |
|-----------|-----|------|------|
| id | integer | PK | 自動 |
| tenant_id | integer | FK→tenants | 自動 |
| invoice_number | string | 請求番号（#XXXX-01形式、枝番対応） | 自動 |
| quote_id | integer | FK→quotes（元見積もり） | No |
| customer_id | integer | FK→customers | Yes |
| currency | enum | JPY / USD / EUR | Yes |
| subtotal | decimal(15,2) | 小計 | 自動計算 |
| shipping_fee | decimal(15,2) | 送料 | No |
| tax_amount | decimal(15,2) | 税額 | No |
| total_amount | decimal(15,2) | 合計 | 自動計算 |
| payment_method | string | 支払方法 | No |
| status | enum | ステータス | Yes |
| exchange_rate_jpy | decimal(10,4) | JPY換算レート | No |
| exchange_rate_usd | decimal(10,4) | USD換算レート | No |
| amount_jpy | decimal(15,2) | JPY換算額 | 自動計算 |
| amount_usd | decimal(15,2) | USD換算額 | 自動計算 |
| pdf_url | string | PDF URL | No |
| issued_at | datetime | 発行日 | 自動 |
| due_date | date | 支払期限 | No |
| paid_at | datetime | 入金日 | No |
| voided_at | datetime | 無効化日 | No |
| void_reason | string | 無効化理由 | No |
| erp_key | string | ERP連携キー | No |
| created_at | datetime | | 自動 |
| updated_at | datetime | | 自動 |

#### データモデル — 請求明細（invoice_items）

| フィールド | 型 | 説明 | 必須 |
|-----------|-----|------|------|
| id | integer | PK | 自動 |
| invoice_id | integer | FK→invoices | Yes |
| product_name | string | 商品名 | Yes |
| quantity | integer | 数量 | Yes |
| unit_price | decimal(15,2) | 単価 | Yes |
| weight | decimal(10,3) | 重量（kg） | No |
| subtotal | decimal(15,2) | 行小計 | 自動計算 |

#### ステータス遷移
```
Draft → Issued → Paid
                → Overdue（期限超過自動遷移）
        → Voided（[VOID]プレフィックス付与、修正戻し対応）
```

#### ビジネスルール
- 発行済み請求書の修正は「修正戻し」（revert）→ 新規発行のフローで対応
- Void時はPDFに[VOID]プレフィックスを付与
- 枝番（-01, -02...）で修正版を追跡
- マルチ通貨対応: 発行時の為替レートを記録し、JPY/USD換算額を自動計算
- ERP連携用の一意キー（erp_key）を自動生成
- 排他ロック: 同一請求書の同時修正を防止

---

### 2.6 注文管理

**概要**: 成約後の注文を管理し、配送・入金までのライフサイクルを追跡する。

#### 現行の実装状態
- 基本CRUD実装済み（customer_id, deal_id, order_number, total_amount, status, notes）

#### 旧システムから移植すべき項目

| フィールド | 型 | 説明 | 必須 |
|-----------|-----|------|------|
| invoice_id | integer | FK→invoices | No |
| currency | enum | JPY / USD / EUR | Yes |
| shipping_carrier | enum | FedEx / DHL / UPS | No |
| shipping_fee | decimal(15,2) | 配送料 | No |
| tracking_number | string | 追跡番号 | No |
| shipped_at | datetime | 発送日 | No |
| delivered_at | datetime | 到着日 | No |
| shipping_country | string | 配送先国 | No |

#### ステータス拡張
```
pending → confirmed → processing → shipped → delivered
                                            → returned
        → cancelled
```

---

### 2.7 在庫管理

**概要**: 商品在庫をリアルタイムで把握し、見積もり・注文時に在庫確認を行う。

#### データモデル（products）

| フィールド | 型 | 説明 | 必須 |
|-----------|-----|------|------|
| id | integer | PK | 自動 |
| tenant_id | integer | FK→tenants | 自動 |
| product_code | string | 商品コード | Yes |
| category | string | カテゴリ | No |
| mark | string | マーク/SKU | No |
| name_en | string | 英語名 | Yes |
| name_ja | string | 日本語名 | No |
| status | enum | 在庫ステータス | Yes |
| condition | string | 状態（新品/中古等） | No |
| unit_price | decimal(15,2) | 単価 | No |
| quantity | integer | 在庫数量 | Yes |
| weight | decimal(10,3) | 重量（kg） | No |
| notes | text | 備考 | No |
| release_date | date | 発売日 | No |
| created_at | datetime | | 自動 |
| updated_at | datetime | | 自動 |

#### 機能要件
- **在庫照会**: カテゴリ・マーク・商品名で検索
- **在庫チェック**: 見積もり/注文作成時に `checkInventory(product_id, quantity)` で在庫引き当て確認
- **在庫数量自動更新**: 注文確定時に在庫を減算、キャンセル時に戻し

---

### 2.8 仕入れ・調達管理

**概要**: 商品の仕入れ先管理と仕入れ発注を行う。

#### データモデル — 仕入れ先（suppliers）

| フィールド | 型 | 説明 | 必須 |
|-----------|-----|------|------|
| id | integer | PK | 自動 |
| tenant_id | integer | FK→tenants | 自動 |
| supplier_code | string | 仕入先コード | 自動 |
| name | string | 仕入先名 | Yes |
| contact_name | string | 担当者名 | No |
| email | string | メール | No |
| phone | string | 電話番号 | No |
| address | text | 住所 | No |
| notes | text | 備考 | No |
| is_active | boolean | 有効/無効 | Yes |
| created_at | datetime | | 自動 |
| updated_at | datetime | | 自動 |

#### データモデル — 仕入れ注文（purchase_orders）

| フィールド | 型 | 説明 | 必須 |
|-----------|-----|------|------|
| id | integer | PK | 自動 |
| tenant_id | integer | FK→tenants | 自動 |
| po_number | string | 発注番号（PO-XXXXX） | 自動 |
| supplier_id | integer | FK→suppliers | Yes |
| status | enum | Draft/Ordered/Received/Cancelled | Yes |
| total_amount | decimal(15,2) | 合計金額 | 自動計算 |
| ordered_at | datetime | 発注日 | No |
| received_at | datetime | 入荷日 | No |
| notes | text | 備考 | No |
| created_at | datetime | | 自動 |
| updated_at | datetime | | 自動 |

#### データモデル — 仕入れ明細（purchase_order_items）

| フィールド | 型 | 説明 | 必須 |
|-----------|-----|------|------|
| id | integer | PK | 自動 |
| purchase_order_id | integer | FK→purchase_orders | Yes |
| product_id | integer | FK→products | Yes |
| quantity | integer | 発注数量 | Yes |
| unit_cost | decimal(15,2) | 仕入単価 | Yes |
| subtotal | decimal(15,2) | 行小計 | 自動計算 |

#### ビジネスルール
- 入荷完了（status=Received）時に在庫数量を自動加算
- 監査ログに仕入れ転記の履歴を記録

---

### 2.9 配送・物流管理

**概要**: 複数キャリアの配送料自動計算と発送管理を行う。

#### データモデル — 配送ゾーン（shipping_zones）

| フィールド | 型 | 説明 |
|-----------|-----|------|
| id | integer | PK |
| tenant_id | integer | FK→tenants |
| country | string | 国名 |
| country_code | string | 国コード（ISO） |
| carrier | enum | FedEx / DHL / UPS |
| zone | string | ゾーン番号 |

#### データモデル — 配送料金（shipping_rates）

| フィールド | 型 | 説明 |
|-----------|-----|------|
| id | integer | PK |
| tenant_id | integer | FK→tenants |
| carrier | enum | FedEx / DHL / UPS |
| zone | string | ゾーン |
| min_weight | decimal | 最小重量（kg） |
| max_weight | decimal | 最大重量（kg） |
| price | decimal(15,2) | 料金 |

#### 機能要件
- **配送料自動計算**: `calculateShippingFee(country, weight_kg, carrier?)`
  - 国からゾーンを検索 → ゾーン＋重量で料金テーブル照合
  - carrier未指定時は3社比較し最安値を返却
- **3社比較見積もり**: 見積もり画面でFedEx/DHL/UPSの料金を並列表示
- **elogiCSV出力**: 配送ラベル用CSVを生成（carrier固有フォーマット）

---

### 2.10 ERP連携

**概要**: CRMの請求データをERPシステムにエクスポートし、データの一貫性を保つ。

#### 機能要件
- **請求書→ERPエクスポート**: 28カラム形式でERP用レコードを構築
  - 送料の按分計算（明細行ごとに割り振り）
  - マルチ通貨換算（JPY/USD）
- **双方向同期**: ERP側の更新をCRMに反映（無限ループ防止あり）
- **同期ステータス管理**: 最終同期日時・結果をレコード単位で記録

> 注: 旧システムではGoogleスプレッドシートのIMPORTRANGEで実現。新システムではAPI連携またはバッチ処理で実装。ERPシステムの仕様確定後に詳細設計。

---

### 2.11 見込み客ランク自動算出

**概要**: リードの属性から自動的に見込度ランクを計算し、営業優先度を可視化する。

#### ランクアルゴリズム

| ランク | 条件 |
|--------|------|
| **A** | 信頼重視 + 大規模 + 24h以内返信 |
| **B+** | 価格重視 + 大規模 + 24h以内返信 |
| **B** | 価格重視 + 中小規模 |
| **B-** | 上記B条件だが反応がやや鈍い |
| **仮C** | C判定要因1つ以上 + 顧客タイプ不明 |
| **確定C** | C判定要因4つ以上 |

#### C判定要因
- 3日以上返信なし
- 想定規模が小規模
- 月間見込み金額 < 100,000円
- 価格重視 + エンゲージメント低

#### ビジネスルール
- 温度感・想定規模・顧客タイプ・返信速度・月間見込み金額の変更時に自動再計算
- ランクはリード一覧・ダッシュボードで視覚表示（色分け）

---

### 2.12 ダッシュボード・KPI

**概要**: 経営・営業の重要指標をリアルタイムで可視化する。

#### 現行の実装状態
- 顧客数、案件数（open/won）、受注数、金額合計は実装済み

#### 旧システムから移植すべきKPI

| カテゴリ | KPI | 説明 |
|---------|-----|------|
| リード | リード数（Inbound/Outbound別） | 流入元別のリード獲得数 |
| リード | コンバージョン率 | リード→案件化の変換率 |
| リード | 必要リード数予測 | 目標案件数に必要なリード数（20%バッファ付き） |
| 営業 | パイプライン金額 | ステージ別の加重金額 |
| 営業 | 案件ステージ分布 | ファネル表示 |
| 営業 | 担当者別成績 | 個人/チーム別の成約数・金額 |
| 財務 | 売上実績 | 期間別（月次/四半期） |
| 財務 | 未入金一覧 | 支払期限超過の請求書 |
| 在庫 | 在庫金額合計 | 商品カテゴリ別 |
| チーム | チーム稼働状況 | アサイン数・対応リード数 |

#### ダッシュボードの種類（権限連動）
| ダッシュボード | 対象ロール |
|---------------|-----------|
| パーソナル | 全ユーザー |
| チーム | チームリーダー以上 |
| マネジメント | マネージャー以上 |
| CS（カスタマーサクセス） | CS担当 |

---

### 2.13 レポート・分析

**概要**: 各種帳票・分析レポートを生成する。

#### 現行の実装状態
- CSV非同期エクスポート（顧客/案件/注文）実装済み

#### 旧システムから移植すべき機能

| レポート種別 | 説明 |
|------------|------|
| 担当者コンバージョン分析 | 担当者別のリード→成約変換率（期間指定可） |
| リードアサイン推奨 | KPI目標に基づく最適なリード配分の提案 |
| 案件レポート | 案件の進捗・停滞状況レポート |
| 日次レポート | スタッフの日次活動サマリー |
| PDF帳票生成 | 見積書・請求書のPDF出力 |

---

### 2.14 ロール・権限管理（Discord式カスタムロール）

**概要**: テナント管理者がロール自体を自由に作成し、リソース×アクション単位で権限を設定できる完全カスタマイズ式RBAC。

#### 現行の実装状態
- admin / user の2値ハードコード

#### 新設計 — データモデル

**roles テーブル**

| フィールド | 型 | 説明 | 必須 |
|-----------|-----|------|------|
| id | integer | PK | 自動 |
| tenant_id | integer | FK→tenants | 自動 |
| name | string(100) | ロール名（例: 営業マネージャー） | Yes |
| color | string(7) | 表示色（#FF5733形式） | No |
| priority | integer | 優先順位（数値が大きいほど上位） | Yes |
| is_system | boolean | システムロール（削除不可） | 自動 |
| description | text | 説明 | No |
| created_at | datetime | | 自動 |
| updated_at | datetime | | 自動 |

**permissions テーブル（マスタ）**

| フィールド | 型 | 説明 |
|-----------|-----|------|
| id | integer | PK |
| key | string | 権限キー（例: customers.view） |
| resource | string | リソース名（例: customers） |
| action | string | アクション名（例: view） |
| description | string | 説明 |
| category | string | 表示カテゴリ |

**role_permissions テーブル**

| フィールド | 型 | 説明 |
|-----------|-----|------|
| id | integer | PK |
| role_id | integer | FK→roles |
| permission_id | integer | FK→permissions |

**user_roles テーブル**

| フィールド | 型 | 説明 |
|-----------|-----|------|
| id | integer | PK |
| user_id | integer | FK→users |
| role_id | integer | FK→roles |
| assigned_at | datetime | 付与日時 |
| assigned_by | integer | FK→users（付与者） |

#### 権限キー一覧（リソース×アクション）

| リソース | 権限キー | 説明 |
|---------|---------|------|
| customers | customers.view | 顧客の閲覧 |
| customers | customers.create | 顧客の作成 |
| customers | customers.edit | 顧客の編集 |
| customers | customers.delete | 顧客の削除 |
| leads | leads.view_own | 自分のリードの閲覧 |
| leads | leads.view_team | チームのリードの閲覧 |
| leads | leads.view_all | 全リードの閲覧 |
| leads | leads.create | リードの作成 |
| leads | leads.edit | リードの編集 |
| leads | leads.delete | リードの削除 |
| leads | leads.assign | リードの担当者変更 |
| deals | deals.view_own | 自分の案件の閲覧 |
| deals | deals.view_team | チームの案件の閲覧 |
| deals | deals.view_all | 全案件の閲覧 |
| deals | deals.create | 案件の作成 |
| deals | deals.edit | 案件の編集 |
| deals | deals.delete | 案件の削除 |
| quotes | quotes.view | 見積もりの閲覧 |
| quotes | quotes.create | 見積もりの作成 |
| quotes | quotes.edit | 見積もりの編集 |
| quotes | quotes.approve | 見積もりの承認 |
| quotes | quotes.delete | 見積もりの削除 |
| invoices | invoices.view | 請求書の閲覧 |
| invoices | invoices.create | 請求書の作成 |
| invoices | invoices.edit | 請求書の編集 |
| invoices | invoices.void | 請求書の無効化 |
| orders | orders.view | 注文の閲覧 |
| orders | orders.create | 注文の作成 |
| orders | orders.edit | 注文の編集 |
| orders | orders.delete | 注文の削除 |
| products | products.view | 商品/在庫の閲覧 |
| products | products.create | 商品の登録 |
| products | products.edit | 商品の編集 |
| products | products.delete | 商品の削除 |
| suppliers | suppliers.view | 仕入先の閲覧 |
| suppliers | suppliers.manage | 仕入先の管理 |
| purchase_orders | purchase_orders.view | 仕入れの閲覧 |
| purchase_orders | purchase_orders.manage | 仕入れの管理 |
| shipping | shipping.view | 配送の閲覧 |
| shipping | shipping.manage | 配送の管理 |
| reports | reports.view_personal | 個人レポートの閲覧 |
| reports | reports.view_team | チームレポートの閲覧 |
| reports | reports.view_all | 全レポートの閲覧 |
| reports | reports.export | レポートのエクスポート |
| dashboard | dashboard.personal | パーソナルダッシュボード |
| dashboard | dashboard.team | チームダッシュボード |
| dashboard | dashboard.management | マネジメントダッシュボード |
| dashboard | dashboard.cs | CSダッシュボード |
| team | team.view | チーム情報の閲覧 |
| team | team.manage | チームの管理 |
| staff | staff.manage | スタッフの管理 |
| roles | roles.view | ロールの閲覧 |
| roles | roles.manage | ロールの作成/編集/削除 |
| roles | roles.assign | ロールの付与/剥奪 |
| settings | settings.view | 設定の閲覧 |
| settings | settings.manage | 設定の変更 |
| admin | admin.access | 管理者パネルへのアクセス |
| admin | admin.force_reset | ユーザーの強制パスワードリセット |
| meta | meta.view | Meta受信トレイの閲覧 |
| meta | meta.send | Metaメッセージの送信 |
| buddy | buddy.view_own | 自分のレポートの閲覧 |
| buddy | buddy.review | レポートのレビュー |
| shift | shift.view | シフトの閲覧 |
| shift | shift.manage | シフトの管理 |

#### Discord式ルール
1. **1ユーザー＝複数ロール**: 権限は全ロールの**和集合**（許可の積み上げ）
2. **priority（優先順位）**: 上位ロール保持者のみが下位ロールを管理可能
3. **owner（テナントオーナー）**: 削除不可・全権限固定のシステムロール
4. **@everyone相当**: テナント作成時に自動生成される最低優先度のデフォルトロール
5. **権限の継承なし**: 各ロールは独立して権限を定義（明示的にONにした権限のみ有効）

#### 初期システムロール（テナント作成時に自動生成）

| ロール名 | priority | 権限 | is_system |
|---------|----------|------|-----------|
| オーナー | 1000 | 全権限 | true |
| メンバー | 1 | 基本閲覧権限のみ | true |

#### 権限チェックロジック（疑似コード）
```python
def has_permission(user, permission_key):
    user_roles = get_user_roles(user.id)
    for role in user_roles:
        if permission_key in role.permissions:
            return True
    return False

def can_manage_role(actor, target_role):
    actor_max_priority = max(r.priority for r in actor.roles)
    return actor_max_priority > target_role.priority
```

---

### 2.15 チーム管理

**概要**: 組織構造を管理し、チーム単位でのデータスコープを制御する。

#### データモデル（teams）

| フィールド | 型 | 説明 | 必須 |
|-----------|-----|------|------|
| id | integer | PK | 自動 |
| tenant_id | integer | FK→tenants | 自動 |
| name | string | チーム名 | Yes |
| leader_id | integer | FK→users | No |
| description | text | 説明 | No |
| is_active | boolean | 有効/無効 | Yes |
| created_at | datetime | | 自動 |
| updated_at | datetime | | 自動 |

#### データモデル（team_members）

| フィールド | 型 | 説明 |
|-----------|-----|------|
| id | integer | PK |
| team_id | integer | FK→teams |
| user_id | integer | FK→users |
| joined_at | datetime | 所属開始日 |

#### データスコープ
- `view_own`: 自分のレコードのみ（assigned_to = current_user）
- `view_team`: 同じチームメンバーのレコード
- `view_all`: テナント内全レコード

---

### 2.16 シフト管理

**概要**: スタッフの勤務シフトを管理する。

#### データモデル（shifts）

| フィールド | 型 | 説明 | 必須 |
|-----------|-----|------|------|
| id | integer | PK | 自動 |
| tenant_id | integer | FK→tenants | 自動 |
| user_id | integer | FK→users | Yes |
| date | date | 勤務日 | Yes |
| start_time | time | 開始時刻 | Yes |
| end_time | time | 終了時刻 | Yes |
| shift_type | enum | 早番/遅番/夜勤/休日 | Yes |
| notes | text | 備考 | No |
| created_at | datetime | | 自動 |
| updated_at | datetime | | 自動 |

---

### 2.17 Meta連携（WhatsApp / Instagram / Messenger）

**概要**: Meta Business APIを通じて顧客とのメッセージングを一元管理する。

#### データモデル — メッセージログ（meta_messages）

| フィールド | 型 | 説明 | 必須 |
|-----------|-----|------|------|
| id | integer | PK | 自動 |
| tenant_id | integer | FK→tenants | 自動 |
| platform | enum | messenger / instagram / whatsapp | Yes |
| sender_id | string | 送信者プラットフォームID | Yes |
| sender_name | string | 送信者名 | No |
| message_text | text | メッセージ本文 | Yes |
| direction | enum | IN / OUT | Yes |
| status | enum | pending / sent / delivered / failed | Yes |
| external_message_id | string | プラットフォーム側メッセージID | No |
| customer_id | integer | FK→customers（紐づけ時） | No |
| created_at | datetime | | 自動 |

#### 機能要件
- **Webhook受信**: Meta Graph APIからのWebhook受信（5秒ルール対応のキュー方式）
- **メッセージ送信**: プラットフォーム別API送信
- **受信トレイUI**: スレッド形式の会話表示
- **連絡先一覧**: 送信者の一覧表示
- **Discord通知連携**: 受信/送信メッセージをDiscordに通知
- **顧客紐づけ**: メッセージ送信者をCRM顧客レコードにリンク

---

### 2.18 Discord通知

**概要**: CRM内の重要イベントをDiscord Webhookで通知する。

#### 通知対象イベント
| イベント | Discordチャンネル |
|---------|-----------------|
| 新規顧客登録 | #crm-activity |
| 案件ステージ変更 | #crm-activity |
| 見積もり承認/却下 | #crm-activity |
| 請求書発行 | #crm-finance |
| 入金確認 | #crm-finance |
| Meta受信メッセージ | #crm-messaging |
| Meta送信メッセージ | #crm-messaging |
| アラート（期限超過等） | #crm-alerts |

#### 設定
- テナント設定でWebhook URLを管理
- 通知のON/OFFはイベント種別ごとに設定可能

---

### 2.19 日報・週報・月報

**概要**: スタッフの活動報告をシステム上で提出・レビューする。

#### データモデル — レポート（staff_reports）

| フィールド | 型 | 説明 | 必須 |
|-----------|-----|------|------|
| id | integer | PK | 自動 |
| tenant_id | integer | FK→tenants | 自動 |
| report_code | string | レポートコード（WR/MR-XXXXX） | 自動 |
| report_type | enum | daily / weekly / monthly | Yes |
| user_id | integer | FK→users（提出者） | Yes |
| period | string | 対象期間（YYYY-MM-DD / YYYY-Wnn / YYYY-MM） | Yes |
| review | text | 振り返り | Yes |
| goals | text | 次期目標 | No |
| challenges | text | 課題 | No |
| self_evaluation | text | 自己評価（月報のみ） | No |
| ai_feedback | text | AI生成フィードバック | No |
| reviewer_id | integer | FK→users（レビュー者） | No |
| reviewer_comment | text | レビューコメント | No |
| reviewed_at | datetime | レビュー日時 | No |
| submitted_at | datetime | 提出日時 | 自動 |
| created_at | datetime | | 自動 |

#### ビジネスルール
- 提出時にAI（Gemini API等）による自動フィードバック生成（オプション）
- マネージャーによるレビュー・コメント機能
- 未提出者へのリマインダー通知（§2.22参照）

---

### 2.20 Buddy/コーチングシステム

**概要**: スタッフ同士のコーチング・メンタリングを支援する。

#### 機能要件
- コーチ/メンティーのペアリング管理
- コーチングセッションの記録
- フィードバック（Good/Bad）の記録と集計
- ナレッジの成功率自動計算
- フィードバック履歴の参照

> 注: 旧システムのBuddyシステムは高度なAI連携を含む。新システムでは段階的に実装し、まずは基本的な記録・集計機能から開始。

---

### 2.21 バッジ・ゲーミフィケーション

**概要**: スタッフのモチベーション向上のためのポイント・バッジシステム。

#### 機能要件
- 実績バッジの定義（例: 初成約、月間MVP、100件対応等）
- ポイント付与ルールの設定
- リーダーボード表示
- バッジ獲得時の通知

---

### 2.22 リマインダー・通知

**概要**: 期限管理・タスクリマインダーをマルチチャンネルで配信する。

#### 通知トリガー
| トリガー | タイミング | 通知先 |
|---------|---------|--------|
| 見積もり有効期限 | 期限3日前、当日 | 担当者 |
| 請求書支払期限 | 期限3日前、当日、超過時 | 担当者+管理者 |
| リードフォローアップ | 最終コンタクトから3日後 | 担当者 |
| 日報未提出 | 当日19:00 | 未提出者 |
| 週報未提出 | 金曜18:00 | 未提出者 |

#### 配信チャンネル
- アプリ内通知（ベル型アイコン）
- Discord Webhook
- メール（将来対応）

---

### 2.23 重複検知

**概要**: 顧客・リードの重複登録を検知し、マージを支援する。

#### 検知ルール
- メールアドレス完全一致
- 電話番号正規化後一致
- 会社名＋担当者名の類似度（レーベンシュタイン距離）

#### マージ機能
- 重複候補の提示
- マスター側を選択してマージ実行
- 関連レコード（案件・注文等）の自動付け替え
- マージ履歴の記録

---

### 2.24 アーカイブ・復元

**概要**: 不要データのアーカイブと必要時の復元を行う。

#### 対象
- 顧客（Inactive化されたもの）
- 失注案件（一定期間経過後）
- 完了注文（一定期間経過後）
- 会話ログ（Meta連携の古いスレッド）

#### ビジネスルール
- アーカイブ時にタイムスタンプを記録
- 復元時は元のステータスを維持
- 監査ログにアーカイブ/復元操作を記録
- 自動アーカイブ（日次バッチ）と手動アーカイブの両方をサポート

---

## 3. 実装優先度（推奨）

### Phase 1 — コア業務基盤（最優先）

| # | 機能 | 理由 |
|---|------|------|
| 2.14 | ロール・権限管理 | 全機能の基盤。先に実装しないと他機能のアクセス制御が組めない |
| 2.1 | 顧客マスタ拡張 | 既存テーブルへのカラム追加。請求先/配送先は見積もり・請求書の前提 |
| 2.2 | リード管理 | 営業パイプラインの入り口 |
| 2.3 | 案件管理拡張 | リードからの変換連携 |
| 2.15 | チーム管理 | データスコープ（own/team/all）の前提 |

### Phase 2 — 販売・財務プロセス

| # | 機能 | 理由 |
|---|------|------|
| 2.7 | 在庫管理（商品マスタ） | 見積もり明細の前提 |
| 2.4 | 見積もり管理 | 販売プロセスの中核 |
| 2.5 | 請求書管理 | 見積もり→請求書の変換フロー |
| 2.6 | 注文管理拡張 | 配送情報の追加 |
| 2.9 | 配送・物流管理 | 送料自動計算 |

### Phase 3 — 営業支援・分析

| # | 機能 | 理由 |
|---|------|------|
| 2.11 | 見込み客ランク | 営業効率化 |
| 2.12 | ダッシュボード拡張 | KPI可視化 |
| 2.13 | レポート・分析拡張 | 意思決定支援 |
| 2.8 | 仕入れ・調達管理 | SCM対応 |
| 2.23 | 重複検知 | データ品質 |

### Phase 4 — コミュニケーション・運用

| # | 機能 | 理由 |
|---|------|------|
| 2.17 | Meta連携 | 外部API依存のため後回し |
| 2.18 | Discord通知 | Webhook設定が前提 |
| 2.22 | リマインダー・通知 | バッチ基盤が前提 |
| 2.19 | 日報・週報・月報 | 運用系 |
| 2.24 | アーカイブ・復元 | 運用系 |

### Phase 5 — 拡張機能

| # | 機能 | 理由 |
|---|------|------|
| 2.10 | ERP連携 | 外部システム仕様の確定が必要 |
| 2.16 | シフト管理 | 補助機能 |
| 2.20 | Buddyシステム | 補助機能 |
| 2.21 | バッジ・ゲーミフィケーション | 補助機能 |

---

## 4. 技術方針メモ

| 項目 | 方針 |
|------|------|
| DB設計 | マルチテナント・スキーマ分離を維持。新テーブルはテナントスキーマ内に作成 |
| API設計 | RESTful `/api/v1/{resource}` を維持。新リソースも同パターン |
| 認証・認可 | Firebase MFA認証を維持。権限チェックはDependency Injectionで統一 |
| PDF生成 | Python側でWeasyPrint等を使用（GASのGoogle Docs連携は不可） |
| バッチ処理 | Celery既存基盤を活用（期限チェック、自動アーカイブ等） |
| 通貨換算 | 外部API（ECB等）からレートを取得し、発行時点のレートを記録 |
| フロントエンド | React + TypeScript + TailwindCSS を維持 |
