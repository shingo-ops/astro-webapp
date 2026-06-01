# ADR-090: products アーキテクチャ統一（tenant別 → public 中央）と Discord取込→在庫表反映

## Status

Proposed —— **しんごさん（PO）承認待ち**。本番データ移行（下流 FK 再マップ）を伴う不可逆性の高い大仕様のため、PO sign-off を経てから実装に着手する。

## Date

2026-06-02（起案: Hikky-dev）

## Context（背景）

在庫表のユーザーフィードバック対応（Phase 2）の着手前調査で、**`products` テーブルが 2 系統に分裂**していることが判明した。

| | `tenant_NNN.products` | `public.products` |
|---|---|---|
| 位置 | テナント別スキーマ（RLS 有） | public（中央・`tenant_id` 全 NULL） |
| 主な列 | `name_ja` / `quantity` / `condition` / `status` / `mark` / `weight` / `notes` | `name` / `stock_quantity` / Box属性（condition/status/mark/weight/notes **無し**） |
| 件数（本番確認） | tenant_006 に **190 行** | **185 行** |
| 読む機能 | **在庫表 `/products`（ProductsPage）** | **Discord取込 INSERT先** ＋ `inventory_search`（見積/請求の商品選択） |

- 両者に同期は無い（`updated_at` トリガのみ）。名前は 185 件一致するが **id 空間は独立**（重複範囲はあるが別商品）。
- **Discord 受信は tenant 非依存**（`discord_inbound_messages` に `tenant_id` 列が無く、`supplier_id` ベースの中央受信）。
- 結果として、**Discord取込（→ public.products）が在庫表（tenant_NNN.products）に反映されない**。「取り込んだ商品が在庫表に出ない」というユーザー報告の根本原因はこれ。

### スペックとの整合

在庫マーケットプレイス spec v1.1 で「**在庫・仕入元・マスタは public 中央共有、顧客/見積/発注はテナント別**」が確定済み。現状 在庫表が `tenant_NNN.products`（レガシー）を読んでいるのは**マーケットプレイス移行の未完部分**であり、本 ADR はその完了に相当する。

### 調査で判明した重大リスク（要 PO 判断）

1. **下流の `product_id` FK が tenant 側に固定**: `quote_items` / `invoice_items` / `purchase_order_items` は `REFERENCES {schema}.products(id)` ＝ **`tenant_NNN.products.id`** を参照（migration 005 / 007）。一方 `inventory_movements` は `public.products(id)` を参照。在庫表を public に切替えると、本番の受発注ドキュメントの商品参照が **id ズレで壊れる** → 既存行の **product_id 再マップ（データ移行）が必須**で、不可逆性が高い。
2. **スキーマ差**: public.products に `name_ja / condition / status / mark / weight / notes` が無い。`/products` router・pydantic schema・ProductsPage の全面改修と、public 側への列追加（additive migration）が必要。
3. **RLS / 権限**: tenant 側は RLS + `products.view/create/update/delete`。public は RLS 無し（中央）。中央在庫表の権限制御をアプリ層で再設計する必要があり、**全テナントが同一の中央在庫を共有**する意味になる。
4. **既存の潜在不整合（移行前に検証すべき前提）**: 見積/請求の作成は既に `InventorySearchBar`（= `public.products.id`）で `product_id` を取得しているのに、`quote_items` の FK は **tenant 側**。つまり**現状でも「在庫検索経由で作った見積」が FK 不整合になりうる**。本移行の前提として、この経路の現行挙動（FK 違反になっているか／id がたまたま重なって通っているか）を実機検証する。

## Decision（決定 / What）

在庫（`products`）を **`public.products`（中央）に一本化**する。

- 在庫表 `/products`（ProductsPage）の読み書き先を `tenant_NNN.products` → `public.products` に移行する。
- 既に `public.products` へ INSERT している Discord取込が、在庫表に**自動的に反映**されるようになる。
- products は**全テナント共通の中央在庫カタログ**となる（マーケットプレイス spec v1.1 の完成）。
- 顧客 / 見積 / 受注など他のテナント別データは**そのままテナント分離を維持**する（本 ADR は products の中央化のみ）。

## Why（なぜ必要か）

- マーケットプレイス spec v1.1（在庫=public中央共有）との整合。
- 「Discord取込 → 在庫表反映」の断絶を解消（ユーザー要望の根本対応）。
- products 二重管理（tenant別／public）の解消。将来の二重不整合バグを根絶。

## Scope（スコープ）

### 含む
1. `public.products` への不足列追加（`condition` / `status` 等の要否は実装フェーズで設計判断。additive-only）。
2. `/products` router + pydantic schema + ProductsPage を public スキーマへ移行（`name_ja ↔ name` / `quantity ↔ stock_quantity` の対応）。
3. 下流 FK（`quote_items` / `invoice_items` / `purchase_order_items`）を `public.products` へ張り替え + **本番 `product_id` の id 再マップ移行**。
4. 中央在庫表の権限制御をアプリ層で再設計。
5. `tenant_NNN.products` の廃止 / 凍結方針の決定。
6. 在庫表 Phase 2 機能（TCG種別マスタ統一・単位列・Discord取込時の言語/状態/単位判定）は、**本一本化の後に上積み**する。

### Scope 外
- 顧客 / 見積 / 受注そのもののテナント分離（維持）。
- 在庫表 Phase 2 の UI 詳細仕様（別途）。

## 段階実装案（How は概略のみ。詳細は実装フェーズ）

- **PR1**: `public.products` への不足列追加（additive migration、ゼロダウンタイム）。
- **PR2**: `/products` router + schema + ProductsPage を public スキーマへ移行（可能なら dual-read で安全に切替）。
- **PR3**: 下流 FK 張り替え + **本番 id 再マップ データ移行**（名前一致 185 件で旧 tenant id → public id のマッピング表を作り `quote_items` 等を UPDATE → FK を public へ張替え）。**destructive のため additive-only 原則の例外 = 本 ADR 承認が証跡**。本番適用は手順書 + バックアップ + PO 立会い。
- **PR4**: `tenant_NNN.products` の凍結 / 廃止。
- **PR5**: Phase 2 機能（種別マスタ統一・単位・取込判定）。

## Consequences（影響）

### ポジティブ
- 取込が在庫表に反映され、ユーザー要望が満たされる。
- products 二重管理の解消。マーケットプレイス設計の完成。

### リスクと対策
- **本番データ移行（FK 再マップ）**: 不可逆。tenant_004（本番 highlife）の products / quote_items / invoice_items / purchase_order_items の**件数と product_id 参照を移行前に SELECT で全把握**し、マッピング不能行（名前不一致・public 未登録）の扱いを事前に決める。バックアップ取得 + ロールバック手順 + PO 立会い。
- **additive-only 原則の例外**: FK 張替えは破壊的。本 ADR の PO 承認をもって例外許可とする（CLAUDE.md / ADR-045 の方針）。
- **権限制御**: RLS 喪失分をアプリ層で担保（`products.*` 権限チェックを public 経路にも適用）。
- **既存潜在不整合（#4）**: 移行前に「在庫検索経由の見積」の現行 FK 挙動を実機検証し、移行で同時に解消する。
- **他テナント影響**: 全テナント共通在庫表になるため、テナント固有商品（tenant_006 の差分 5 件等）の扱いを移行時に決める。

## Open Questions（PO 確認事項）

1. 全テナント共通の中央在庫表で運用上問題ないか（テナント固有の非公開商品が必要なケースは無いか）。
2. `tenant_NNN.products` 上の既存データ（tenant_006 の 190 件のうち public に無い 5 件等）を public へ統合するか、破棄するか。
3. 本番 FK 再マップ移行のタイミング（メンテ枠 / ダウンタイム許容度）。

## 関連 ADR / ドキュメント

- ADR-072（products は tenant schema prefix・現行運用）← 本 ADR で products に関する部分を更新。
- ADR-083（`tcg_type_master`）/ Phase 2 の種別統一はこのマスタを利用。
- `docs/products_design.md`（tenant products の Phase 1-C 設計）← 本 ADR で中央化方針に更新。
- 在庫マーケットプレイス spec v1.1（在庫=public中央共有）← 本 ADR はその完成。
- 在庫表 Phase 1（PR #1368, merged）とは独立。Phase 2 機能は本統一の後に乗せる。
