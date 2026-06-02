# ADR-093: 在庫表 / 仕入元オファー / 商品マスタ 再設計

## Status
Accepted

ひとしさん（PO 代理・開発）からの要件を本セッションで確定（2026-06-02）。Reviewer エージェント検証を経てマージ予定。

## Date

2026-06-02（起案: Hikky-dev）

## Context（背景）

最終ユーザー向けの「在庫表」(`/inventory`) は現在 **商品マスタ(`public.products`)** を表示しており
在庫数は常に 0 で表示される。一方 Discord 受信の取り込み（承認）は
**`public.inventory`（仕入元オファー）** にのみ反映される。このため「取り込んだのに在庫表に
出てこない」というズレが発生していた。

合意済みの運用フロー:
**管理者が Discord 受信通知から取り込み → 即「在庫表」に反映 → 管理者が「仕入元現在オファー」
画面で編集/削除** を成立させる。あわせて、商品マスタの編集導線・予約商品(Pre-order)/発送日/形態の
軸・最終ユーザー向けのフィルタを整備する。

## Decision（What / Why / Scope）

### 確定した仕様（ひとしさん回答 2026-06-02）

1. **在庫表はオファー表示の読み取り専用に作替え。** 編集/削除は「仕入元現在オファー」
   (`/super-admin/inventory-offers`) に集約。商品マスタ CRUD は専用の管理画面へ移設。
2. **価格は単価(`unit_price`)1本。** 仕入価格と販売価格の分離はしない（在庫表は単価のみで十分）。
   将来 販売価格カラムを追加してもやり直し不要な additive 設計とする。
3. **商品マスタは「商品マスタ.csv」相当の全項目を編集可能にする。**
   `public.products` に未実装の 7 列（`volume_weight` / `search_keywords` / `exclude_keywords` /
   `related_series` / `category_classification` / `required_output_value` / `item`）を additive 追加。
   既に DB に在るが API/UI 未露出の Box 属性 7 列（`boxes_per_case` / `packs_per_box` /
   `box_weight_kg` / `case_weight_kg` / `moq` / `hs_code` / `material`, migration 082）も露出する。
   `required_output_value` / `item` は **発送ラベル用（HSコード検索等）** の情報。
   レアリティ(`rarity`)はシングルカード用属性で封入品(Box/Case)には実値が無く、在庫表からは除外する。
4. **予約商品(Pre-order)** を導入。在庫(In Stock)と対比し、`offer_type`(in_stock / pre_order) と
   発送日 `ship_timing`（`on_release`=発売日発送 / `1day_before` / `2day_before` / `other`）を
   `public.inventory` に追加。形態(Box/Case) は既存 `unit` を流用。在庫表の 1 行は
   **商品 × 仕入元 × 状態(condition) × 形態(unit) × 区分(offer_type) × 発送日(ship_timing)** の
   組合せで決まる（オファーの UNIQUE キーを拡張）。在庫品は `ship_timing` = NULL。
5. **在庫表のフィルタ**: 最終ユーザー（各クライアントの**営業担当ロール以上**、`products.view` 権限）が
   ヘッダーからフィルタ（ポップアップ）でき、仕入元の表示/非表示（複数選択）と列の取捨を
   制御できる。設定は **ユーザー別に永続化**し再ログイン後も保持、ON/OFF トグルで一括制御。
6. **在庫表は横スクロールを極力しないレイアウト**（関連項目を複合セルに集約し実質 5 列に圧縮、
   任意列は既定非表示で列トグル、狭幅はカード折返し）。

### Scope（段階導入）

- **Phase 1**: 商品マスタの全項目編集（`public.products` 7 列追加 + 既存 Box 属性 7 列の API/UI 露出）。
- **Phase 2**: 在庫表(`/inventory`) をオファー表示の読み取り専用へ作替え（列再構成・レアリティ削除・
  掲載時間=Discord 受信時刻 追加）。商品マスタ CRUD を専用管理画面へ分離。
- **Phase 3**: `public.inventory` に `offer_type` / `ship_timing` 追加 + UNIQUE キー拡張、取り込み解析・
  オファー編集・在庫表表示の対応。
- **Phase 4**: ユーザー別フィルタ（ポップアップ / 仕入元複数選択 / 列トグル / ON-OFF / 永続化）。

### Out of Scope

- 販売価格カラム（マージン管理）。在庫表は単価のみ。
- レアリティの在庫表表示。
- 商品マスタの CSV 一括取込・pokeapi/TCG マスタからの自動補完（最初は手入力。将来別 ADR）。

## Consequences（影響）

- `public.products` への additive な列追加のみ（削除・型変更なし、ゼロダウンタイム）。
- Discord 取り込みが在庫表に反映され、運用フローの認知ズレが解消する。
- オファーの UNIQUE キー拡張（Phase 3）に伴い `inventory_movements` の UPSERT・解析・編集 UI の
  改修が必要（同 PR で整合させる）。

## 参照

- 既存実装: `public.products`(migration 062 / 082 / 20260602_000000 系), `public.inventory`(migration 081),
  在庫表 `frontend/src/pages/products/ProductsPage.tsx`, 仕入元オファー
  `frontend/src/pages/super-admin/InventoryOffersPage.tsx`
- ADR-090（products を public 中央へ一本化）, ADR-089（companies SSOT）
- メモ: GAS Exclude Keywords 54 件の未移植ギャップ（`exclude_keywords` 列が移植先）
