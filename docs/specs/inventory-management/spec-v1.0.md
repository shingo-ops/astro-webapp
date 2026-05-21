# Jarvis CRM 在庫管理機能整備（仕入受信〜営業フロー連鎖）

> 注: このリポジトリの直前 `spec.md` は ADR-021 Sprint 5（Sales Anchor / shingo-ops）の起案で、本仕様とは別件。前版は `.claude-pipeline/spec-prev-adr021-sprint5.md` に退避済み。

## Overview

Jarvis CRM（HIGH LIFE JPN / Treasure Island JP の B2B SaaS CRM、本番テナント `tenant_004 / highlife-jpn`）は Phase 1〜2 で商品・顧客・見積・請求・発注の基本 CRUD と Phase 1-C M-MVP で TCG B2B 輸出向けの 11 列拡張（migration 038、`jan_code/card_number/expansion_code/rarity/language/unit_price_usd|eur/image_url/is_archived/archived_at/supplier_default_id`）まで完了している。一方、現場の在庫運用は依然として Google スプレッドシート（45 仕入元、複数 TCG マスタ、API 解析シート、正規化在庫リスト）に依存しており、Discord で届く仕入元メッセージの正規化〜在庫反映〜営業活動への連携が CRM に取り込まれていない。

本スプリント群は、この **Discord 受信 → 正規化解析（ルール＋LLM ハイブリッド）→ 担当者承認 → 在庫反映 → 営業（在庫検索・見積・発注書）連携** の一気通貫を CRM 側に実装し、スプレッドシートを Phase A（並走）→ Phase B（書込切替）→ Phase C（閉鎖）で段階的に廃止する。新規実装ではなく、既存資産（`backend/migrations/005|007|038`、`discord_gateway/` M2 段階、Meta webhook HMAC 検証パターン、`ProductsPage/QuotesPage/QuoteCreatePage/PurchaseOrdersPage/SuppliersPage` などの React ページ、Phase 1 の `require_permission()` パターン、ADR-027 i18n、ADR-034 で整備中の新規テナント migration 自動適用）をすべて拡張ベースで活用する。

対象ユーザーは admin（マスタ編集・解析結果承認・PO 発行）、サポート / 営業（在庫検索・見積・問い合わせ応答）、観測者（読み取り）。45 仕入元には個人名・法人名が混在し、商品マスタは現状ポケモン・トレーナー図鑑（合計 1025+α）と Pokemon Booster Box / One Piece / Dragon Ball / Union Arena / 遊戯王 のシリーズマスタを横断する。

## Goals

- **G1**: 仕入元 Discord メッセージを 1 メッセージ＝1 件単位で受信・保存・正規化し、担当者が確認・承認すると `products` の在庫数・参考価格・状態が更新される。
- **G2**: 45 仕入元それぞれの言い回しを `supplier_aliases` で学習し、PO（発注書）PDF / メール送信時に該当仕入元固有の表記へ自動置換できる。
- **G3**: 営業がスプレッドシートを開かず、CRM 内の在庫検索 → 見積作成 → 顧客送付までを一気通貫で完了できる。
- **G4**: 解析は **ルール＋辞書優先・失敗時のみ Claude API フォールバック** のハイブリッドで、テナント月次 LLM コスト上限を設定可能（超過時の挙動は Q2 確認）。
- **G5**: 段階的廃止 Phase A → B → C を運用可能な手順とトグルで実装し、スプレッドシート併用期間中も整合を保つ。

## Non-Goals

- スプレッドシートからの全自動同期 API ブリッジ（読み取り専用の CSV エクスポートで対応、双方向同期は対象外）。
- TCG 価格情報の外部ソース自動取得（USD/EUR の自動同期、TCGPlayer 等の API 連携）。
- 在庫の物理ロケーション管理（倉庫棚位置、ロット管理）。
- 仕入元との Discord 上での自動返信ボット（Bot は受信専用、能動応答は本スプリント群対象外）。
- LLM プロバイダーの抽象化レイヤー（Claude API 固定で実装、別プロバイダー対応は別 ADR）。
- 既存 ADR-034（新規テナント migration 自動適用）の代替実装。本仕様の migration はすべて ADR-034 経由で適用される前提。

## User Personas

- **Admin（しんごさん）**: マスタ編集、解析失敗のレビュー、承認フロー閾値変更、LLM コスト上限設定、Phase 切替を担当。`master.*.edit` 系権限保持。
- **サポート/営業担当**: 在庫検索、見積作成、顧客問い合わせ応答、解析結果の確認・承認（admin 委任時）。`inventory.view`, `quotes.create`, `parse_review.approve` 保持。
- **仕入担当**: PO 起票、仕入元別 alias の補正、解析結果の差分確認。`purchase_orders.create`, `supplier_aliases.edit`。
- **観測者（経理 / 役員）**: 読み取り専用で在庫・売上・PO の状態を閲覧。

## Features

### F1: スキーマ基盤と既存マスタ初期投入

- **Description**: 在庫パイプラインのデータ基盤を 1 つの migration バンドル（047〜053）で導入する。Phase 1-C 038 と衝突しないよう products は拡張のみ（列追加 / インデックス追加）に留める。すべて ADR-034 経由で全テナント＋新規テナントへ自動適用される。
- **既存資産参照**:
  - `astro-webapp/migrations/005_*.sql`（products, quotes, invoices）
  - `astro-webapp/migrations/007_*.sql`（suppliers, purchase_orders）
  - `astro-webapp/migrations/038_add_products_phase1c_columns.sql`
  - `astro-webapp/migrations/044_create_meta_page_routing_trigger.sql`（マルチテナント trigger 参考）
- **新規 migration（提案番号、最新 046 の次から、ADR-034 適用順を維持）**:
  - `047_create_supplier_aliases.sql` — `(id, tenant_id, product_id, supplier_id, alias_text, language CHAR(2) DEFAULT 'ja', confidence NUMERIC(4,3), source TEXT, created_by, created_at, updated_at, UNIQUE(tenant_id, supplier_id, alias_text, language))`
  - `048_create_knowledge_rules.sql` — `(id, tenant_id, category, pattern_type, pattern, normalized_to, priority INT, language CHAR(2), is_active BOOLEAN, created_by, created_at)`
  - `049_create_discord_inbound_messages.sql` — `(id, tenant_id, supplier_id, discord_channel_id, discord_message_id, raw_content, received_at, parse_status, parse_engine, parse_result_json JSONB, exclude_reason, operator_comment, llm_cost_usd NUMERIC(8,4), UNIQUE(tenant_id, discord_message_id))`
  - `050_create_supplier_discord_routing.sql` — `(id, tenant_id, supplier_id, discord_guild_id, discord_channel_id, is_active, UNIQUE(discord_guild_id, discord_channel_id))`
  - `051_create_tcg_and_dex_masters.sql` — `pokemon_dex(id, dex_number, name_ja, name_en, generation, region)`, `trainer_dex(id, dex_number, name_ja, name_en, era)`, `tcg_series_master(id, tcg_type, series_code, name_ja, name_en, release_date, category)`（全テナント共有 = `public` schema、Q6 で確定）
  - `052_create_inventory_movements.sql` — `(id, tenant_id, product_id, delta_qty, before_qty, after_qty, source_type, source_id, supplier_id, operator_id, occurred_at, notes)` source_type ∈ {discord_message, manual, purchase_order, sale}
  - `053_create_llm_budget.sql` — `tenant_llm_budgets(tenant_id PK, monthly_budget_usd, current_month_usd, last_reset_at, hard_stop BOOLEAN)`、`discord_webhook_idempotency` テーブル（Meta `meta_webhook_idempotency` 流用、`discord_message_id` PK + `received_at`）
- **マスタ初期投入スクリプト**: `scripts/seed_pokemon_dex.py`, `scripts/seed_tcg_series.py`, `scripts/seed_suppliers_from_sheet.py`（CSV 入力、冪等、`scripts/migrate_meta_*` のスクリプト構造踏襲、`astro-webapp/sheets/` 配下の既存 CSV と同列に配置）
- **User stories**:
  - 「admin として、新規テナントを作るとき在庫管理に必要なテーブルがすべて自動で作成されてほしい（ADR-034 経由）」
- **Acceptance criteria**:
  - **AC1.1**: PostgreSQL（VPS の `tenant_004` および `tenant_006`）に対し、migration 047〜053 を順序適用後、`information_schema.tables` で全 8 テーブルの存在を確認できる（SQLite モックではなく実 Postgres で）。
  - **AC1.2**: `supplier_aliases` に `(tenant_id, supplier_id, alias_text, 'ja')` の重複 INSERT を試行すると UNIQUE 制約で 23505 が返る。
  - **AC1.3**: 新規テナント `qa-ephemeral-fNN` を `scripts/qa/create-fresh-tenant.sh` で作成し、`information_schema.columns` で 8 テーブルの列構成を取得、全テナント間で同一であることを diff で確認。
  - **AC1.4**: `scripts/seed_pokemon_dex.py --dry-run` で 1025 行の検証ログ、`--apply` で `public.pokemon_dex` に 1025 行が挿入される。二度実行しても件数は変わらない（冪等）。
  - **AC1.5**: Playwright が backend `/api/v1/admin/migrations/status` を叩いて 047〜053 すべて applied=true を確認するスモークシナリオが green。
  - **AC1.6**: `discord_webhook_idempotency` の構造は既存 `meta_webhook_idempotency`（migration 040 系）と一致しており、Reviewer agent が diff で確認できる。

### F2: マスタ編集 UI（admin 4 タブ）

- **Description**: `/admin/masters` ルート配下に 4 タブを設置。すべて admin 権限ベースで CRUD + CSV import/export。i18n 準拠（ADR-027）。既存 `SuppliersPage.tsx` は 4 タブ目に取り込み、admin 専用機能を追加。
- **既存資産参照**:
  - `astro-webapp/frontend/src/pages/SuppliersPage.tsx`（仕入元 CRUD ベース）
  - `astro-webapp/frontend/src/pages/RolesPage.tsx`（admin 専用ページパターン）
  - `astro-webapp/backend/app/auth/dependencies.py`（`require_permission` パターン）
  - `astro-webapp/frontend/src/locales/ja.json`, `en.json`（i18n キー）
- **新規 UI 構造**:
  - `pages/admin/MastersPage.tsx`（タブコンテナ）
  - `pages/admin/KnowledgeAliasesTab.tsx`（全文検索＋一括 CSV import/export、行編集）
  - `pages/admin/TcgSeriesTab.tsx`（5 TCG タイプの select + テーブル）
  - `pages/admin/DexTab.tsx`（ポケモン / トレーナー切替）
  - `pages/admin/SuppliersAdminTab.tsx`（既存 `SuppliersPage` 拡張 + `supplier_discord_routing` 紐付け UI）
- **権限**: `master.knowledge.edit`, `master.tcg.edit`, `master.dex.edit`, `master.supplier.edit`（migration 053 のシード追加 or 別 seed migration）
- **User stories**:
  - 「admin として、新しい仕入元が独特な略語を使い始めたら knowledge_rules に追加して以後の解析に反映したい」
  - 「admin として、CSV で図鑑を一括差し替えしたい（ポケモン公式が新作を出したとき）」
- **Acceptance criteria**:
  - **AC2.1**: Playwright が `/admin/masters` にアクセスし、admin 以外の staff ロールで開くと 403 / redirect、admin で開くと 4 タブが表示される（実 backend、tenant_006 で）。
  - **AC2.2**: Knowledge タブで新規 rule（pattern_type=regex, pattern=`^PSV1a-(\d+)`, normalized_to=`SV1a-$1`, language=ja）を作成 → 保存 → 一覧に表示 → DB に行が存在することを SQL で確認できる。
  - **AC2.3**: TCG タブで Pokemon Booster Box の `SV1a` 行を編集 → 保存 → `public.tcg_series_master` に反映、ja/en 両方の表示が i18n キー経由で切り替わる。
  - **AC2.4**: Dex タブでポケモン #25 の英名を編集して保存 → `public.pokemon_dex` 更新 → 再読み込みで反映。
  - **AC2.5**: Suppliers タブで仕入元 #3 に Discord guild_id / channel_id を割り当て → `supplier_discord_routing` に行が追加され、`is_active = true` で保存される。
  - **AC2.6**: CSV import: 不正フォーマット（必須列欠落）の CSV をアップロード → エラーメッセージが i18n キー経由で表示、DB は変化なし。正常 CSV では行数差分が表示され、確認後 commit される。
  - **AC2.7**: i18n grep: `git diff frontend/src/pages/admin/` で日本語ハードコード残骸 0 件、`ja.json/en.json` に同一キーが存在する。

### F3: ルールベース解析エンジン

- **Description**: `backend/app/services/inventory_parser.py` を新設し、`knowledge_rules` ＋ `supplier_aliases` を使って raw_content を構造化 JSON に正規化するパイプラインを実装。LLM 呼び出しは F4 で追加、本機能はルールのみ。
- **既存資産参照**:
  - `astro-webapp/backend/app/services/`（既存 service レイヤパターン）
  - `astro-webapp/backend/tests/`（pytest baseline）
- **パイプライン仕様**:
  - 入力: `raw_content: str, supplier_id: int, language: str`
  - Step 1: 行単位に分割 → exclude pattern（例: header / footer）で除外
  - Step 2: 各行に対し `supplier_aliases` で alias_text 完全 / 部分一致探索 → product_id を解決
  - Step 3: 残り行に `knowledge_rules`（priority 降順）を順次適用 → tcg_series_master / dex で product 候補を引く
  - Step 4: 数量・単価・状態を行内 token から抽出（正規表現セットを `knowledge_rules` から動的構築）
  - 出力: `ParseResult { items: [...], excludes: [...], unparsed: [...], parse_engine: "rule_v1" }`
- **冪等性**: 同一 `(supplier_id, raw_content)` 入力に対し常に同一出力（決定論的）
- **Acceptance criteria**:
  - **AC3.1**: 単体テスト 30 ケース以上を `backend/tests/test_inventory_parser_rule.py` に追加し、すべてのケースで期待 `items / excludes / unparsed` の数を assert（モックデータでなく実 supplier_aliases フィクスチャ）。
  - **AC3.2**: 実 Postgres（tenant_006）に supplier_aliases / knowledge_rules を seed した状態で、実在の 45 仕入元から取得した raw_content サンプル 5 件（しんごさんから取得）を service に渡し、`parse_status = parsed` で返ることを確認。
  - **AC3.3**: 同一 raw_content を 2 回流すと完全に同じ output JSON（順序まで）が返る。
  - **AC3.4**: alias 未登録の token は `unparsed` に分類され、`exclude_reason` ではなく `parse_result_json.unparsed` に格納される。
  - **AC3.5**: 解析速度ベンチ: 1000 行 raw_content を 5 秒以内に処理（VPS 2GB 環境、R5 observability SLO 内）。

### F4: LLM フォールバック（Claude API）と コスト管理

- **Description**: F3 が `unparsed` を返した行のみ Claude API へフォールバックする。プロンプトには raw_content + knowledge_rules スナップショット + 出力スキーマを含める。コストは `tenant_llm_budgets` で月次集計し、hard_stop 設定時は上限超過で fallback を停止して `parse_status = budget_exhausted` を記録。
- **既存資産参照**:
  - `astro-webapp/backend/app/services/` 配下に既存 LLM 呼び出しがあれば流用（無ければ新規 `llm_client.py`）
- **新規ファイル**:
  - `backend/app/services/inventory_parser_llm.py`
  - `backend/app/services/llm_budget.py`
- **環境変数**: `CLAUDE_API_KEY`（既存 secret 体系、deploy.yml の sed 追加方式に従う、ADR-025 trap 回避）
- **Acceptance criteria**:
  - **AC4.1**: F3 で unparsed が 1 行以上ある raw_content を流す → Claude API を 1 回呼ぶ → `parse_result_json` に LLM 由来 items がマージされる。tenant_006 で実 API key を使って 1 経路通す（モックではなく）。
  - **AC4.2**: `discord_inbound_messages.llm_cost_usd` に API 応答の usage トークンから算出した実コストが記録される。
  - **AC4.3**: `tenant_llm_budgets.monthly_budget_usd = 0.01` に設定し、超過するまで 5 件流す → 超過後の 1 件は `parse_status = budget_exhausted, parse_engine = rule_v1_fallback_blocked` で API 呼び出しなし。
  - **AC4.4**: 月初の `last_reset_at` が変わると `current_month_usd` が 0 にリセットされる（cron or 起動時 check）。
  - **AC4.5**: API キー欠落 / 不正時の挙動: rule_v1 のみで処理し、parse_status = `parsed_rule_only` で記録、500 エラーにしない。
  - **AC4.6**: Playwright で admin が `/admin/masters` → LLM 設定タブ（既存 4 タブに加え）から budget を編集 → 即時反映される。

### F5: Discord Bot 受信（M3 段階 / ADR-009 拡張）

- **Description**: `discord_gateway/client.py` を ADR-009 M2 から M3 に拡張し、`on_message_create` イベントを購読。`supplier_discord_routing` で照合し、該当チャンネルからのメッセージを `discord_inbound_messages` に保存 → 解析キュー（in-process 非同期 task）へ投入。冪等性は `discord_webhook_idempotency` で保証。HMAC 署名検証は **Meta webhook の `X-Hub-Signature-256` 流用パターン**（`backend/app/routers/webhook.py` L268-275 と同型）を採用するが、Discord は Bot Gateway 経由（WebSocket）が主で署名は Discord 側 token 検証に変わる点を明記（HTTP outbound webhook 化する場合のみ HMAC 必要）。
- **既存資産参照**:
  - `astro-webapp/backend/app/discord_gateway/client.py`（M2 段階）
  - `astro-webapp/backend/app/discord_gateway/main.py`
  - `astro-webapp/backend/app/routers/webhook.py`（HMAC 検証コード L268-275、`hmac.compare_digest` パターン）
  - `astro-webapp/migrations/040_create_tenant_meta_config.sql`、`041_extend_meta_messages.sql`（webhook idempotency 系の先例）
- **Acceptance criteria**:
  - **AC5.1**: 実 Discord サーバー（しんごさん管理下のテスト guild）に Bot を招待 → channel #test-inventory に「テスト在庫メッセージ」を投稿 → 5 秒以内に `discord_inbound_messages` に 1 行追加され、`parse_status = pending` で待機する（モックではなく実 webhook）。
  - **AC5.2**: 同一 `discord_message_id` を 2 回受信 → 1 行のみで、`discord_webhook_idempotency` に 1 行記録、Discord 側へは 200 OK 返却。
  - **AC5.3**: `supplier_discord_routing` に登録されていない guild からのメッセージは `parse_status = ignored_routing` で記録され、F3 解析は走らない。
  - **AC5.4**: Bot が Discord 切断 → 再接続後の missed messages を REST `channel_messages` で補完取得し、漏れなく `discord_inbound_messages` に追加（Q1 とは別、技術仕様）。
  - **AC5.5**: Playwright が「admin で Inbound メッセージ一覧」画面（`pages/inbound/DiscordInboundPage.tsx`、新規）を開き、tenant_006 に POST した実 webhook 由来のメッセージ 3 件が時系列降順で表示される。

### F6: 解析結果レビュー UI と在庫差分反映

- **Description**: 解析済 `discord_inbound_messages` の `parse_result_json` を担当者が UI でレビュー → 商品ごとに「採用 / スキップ / 編集」操作 → 承認すると `inventory_movements` に行を追加し、`products.stock_quantity` を更新（Q1 確認後の閾値運用に応じて自動承認分岐）。
- **既存資産参照**:
  - `astro-webapp/frontend/src/pages/SuppliersPage.tsx`（一覧 UI パターン）
  - `astro-webapp/backend/app/routers/products.py`（products 更新エンドポイント）
- **新規ファイル**:
  - `frontend/src/pages/inbound/DiscordInboundPage.tsx`
  - `frontend/src/pages/inbound/ParseReviewPage.tsx`
  - `backend/app/routers/parse_review.py`
- **Acceptance criteria**:
  - **AC6.1**: Playwright が「未承認」フィルタで 1 件を開き、行ごとの採用 / スキップを操作 → 承認 → `inventory_movements` に該当行数の INSERT、`products.stock_quantity` が delta_qty だけ増減。
  - **AC6.2**: 承認後、`discord_inbound_messages.parse_status = approved`、`operator_comment` に reviewer の任意メモが入る。
  - **AC6.3**: スキップした行は `parse_result_json.skipped[]` に保存され、再 review 時に履歴として参照できる。
  - **AC6.4**: 差し戻し（reject）操作で `parse_status = rejected` + `exclude_reason` 必須記録、`products` 無変化。
  - **AC6.5**: 同一メッセージを別ユーザーが同時に承認しようとすると後勝ち禁止（楽観ロック or 409 conflict）。
  - **AC6.6**: 在庫差分は `inventory_movements` の append-only 形式で保持され、`products.stock_quantity` の現値と `SUM(delta_qty) over inventory_movements` が常に一致（DB 制約 or assertion）。
  - **AC6.7**: i18n: レビュー画面のすべての UI 文言が `t("inbound.review.*")` 経由、ja/en 同期。

### F7: 営業向け在庫検索 UI と見積画面連携

- **Description**: 営業画面に在庫検索を追加。日本語 / 英語 / expansion_code / JAN / supplier_alias 横断検索（Q5 で確定する検索式）。既存 `QuoteCreatePage.tsx` の商品選択をこの検索 component に置換し、選択時は商品の標準名（products.name）で見積行に乗せる。
- **既存資産参照**:
  - `astro-webapp/frontend/src/pages/QuoteCreatePage.tsx`
  - `astro-webapp/frontend/src/pages/QuoteDetailPage.tsx`
  - `astro-webapp/backend/app/routers/products.py`（既存検索エンドポイント）
- **新規ファイル**:
  - `frontend/src/components/InventorySearchBar.tsx`
  - `backend/app/routers/inventory_search.py`（`GET /inventory/search?q=...&lang=...`）
- **Acceptance criteria**:
  - **AC7.1**: Playwright で営業 user として `/quotes/new` を開き、検索バーに「リザードン」と入力 → 候補に日本語名一致 + 英名 Charizard が含まれる（pokemon_dex 横断）。
  - **AC7.2**: 検索バーに `SV1a-001` を入力 → 該当 card_number の product が候補トップに来る。
  - **AC7.3**: 検索バーに supplier alias「リザeXSAR」を入力 → `supplier_aliases` 解決経由で標準名 product が候補に出る。
  - **AC7.4**: 候補から 1 件を選択 → quote_items に標準名 + 標準 unit_price で行追加。
  - **AC7.5**: 在庫 0 商品は候補末尾 / グレーアウト表示で、選択時に警告（既存 toast パターン）。
  - **AC7.6**: 検索 API レスポンス時間: tenant_006 seed (5 products) で 200ms 以内 / tenant_004 本番見立て (1000 products 想定) で 500ms 以内。
  - **AC7.7**: i18n: 検索 placeholder, 警告メッセージすべて `t()` 経由。

### F8: PO（発注書）拡張 — aliases 置換 + PDF + メール

- **Description**: 既存 `PurchaseOrdersPage.tsx` を拡張。内部表示は商品標準名、PDF / メール送信時のみ `supplier_aliases` から該当仕入元の alias_text に自動置換。PDF は既存 invoice の PDF パイプライン流用、メールは既存 SMTP（無ければ新規 ADR 起案を Q として明記）。
- **既存資産参照**:
  - `astro-webapp/frontend/src/pages/PurchaseOrdersPage.tsx`
  - `astro-webapp/backend/app/routers/purchase_orders.py`
  - `astro-webapp/backend/app/services/`（既存 PDF 生成があれば流用、invoices.py 系の PDF 機能）
- **新規ファイル**:
  - `backend/app/services/po_renderer.py`（alias 置換 + テンプレ）
  - `backend/app/services/po_mailer.py`
- **Acceptance criteria**:
  - **AC8.1**: PO 詳細画面で「PDF ダウンロード」を押す → ブラウザがダウンロードしたファイルを Playwright が受信 → PDF 内の商品名が `supplier_aliases.alias_text`（該当仕入元の言い回し）に置換されている（pdfminer で text extract して assert）。
  - **AC8.2**: 「メール送信」を押す → 仕入元の email 宛に PDF 添付メールが送信される（テスト環境では mailtrap / mailhog にキャプチャ）→ 件名 / 本文に標準名が含まれず alias_text のみ含まれる。
  - **AC8.3**: 該当仕入元に alias 未登録の商品は標準名のままレンダリングされ、PDF 末尾の「Notes」欄に「alias 未登録: <product_name>」が列挙される。
  - **AC8.4**: alias が ja/en 両方ある場合は仕入元の `default_language` に従う（suppliers テーブルに列追加 = migration 048 に同梱、または既存列流用）。
  - **AC8.5**: メール送信失敗時は PO ステータスが `sent` にならず、`error` で記録、再送ボタンが表示される。
  - **AC8.6**: 既存 PO の一覧 / 編集機能はリグレッションなし（Playwright e2e で確認）。

### F9: 段階的廃止 Phase A / B / C 切替

- **Description**: スプレッドシート併用から CRM 単独運用への移行を 3 段階で切り替える運用機能と admin UI トグル。Phase 状態は `tenant_settings.spreadsheet_phase` ENUM('A', 'B', 'C') に保持し、Phase ごとにシステム挙動が変わる。
- **既存資産参照**:
  - `astro-webapp/migrations/040_create_tenant_meta_config.sql`（tenant_settings 系の先例）
- **Phase 定義**:
  - **Phase A（並走）**: CRM 側で受信・解析・表示まで実装、`products.stock_quantity` の真値はスプレッドシート、CRM は読み取り＋表示のみ。承認操作はスプレッドシートにも CSV エクスポートで反映可能（手動）。
  - **Phase B（書込切替）**: CRM 側 `products` を正本、スプレッドシートは GAS で `/api/v1/products` を読み取り表示専用ビュー化（Q3 で確定する世代保持と合わせて）。承認操作で CRM 在庫が変動、スプレッドシートは参照のみ。
  - **Phase C（閉鎖）**: スプレッドシート閉鎖、過去データの CSV エクスポートを CRM へ完全移行（バルク import スクリプト）。
- **新規ファイル**:
  - `migrations/054_add_spreadsheet_phase.sql`（tenant_settings に列追加）
  - `frontend/src/pages/admin/PhaseSwitchPage.tsx`
  - `backend/app/services/phase_gate.py`（Phase に応じた write 抑制 / 警告）
  - `scripts/export_inventory_for_sheet.py`（Phase A の CSV 出力）
  - `scripts/import_inventory_from_sheet.py`（Phase C の最終移行）
- **Acceptance criteria**:
  - **AC9.1**: Phase A 設定下で F6 の承認操作を実行 → `inventory_movements` には記録されるが `products.stock_quantity` は変化せず、warning toast「Phase A: スプレッドシート併走中、在庫数の真値は GS」が表示。
  - **AC9.2**: Phase B 設定下で同操作 → `products.stock_quantity` が変動、警告なし。
  - **AC9.3**: Phase C 設定下で初回起動時、`/api/v1/admin/import-from-sheet` を実行 → 過去 CSV を読み込み products へ反映、二重投入防止（同 product_id の上書きでなく skip）。
  - **AC9.4**: Phase 切替は admin のみ可能、`require_permission("phase.switch")`。
  - **AC9.5**: Playwright で Phase A → B → C と切り替え、各段階で承認操作の挙動が AC9.1〜9.3 通り変わることを 1 シナリオで確認。
  - **AC9.6**: Phase 切替履歴が `audit_log`（既存 or 新規）に記録される。

## User Flows

### UF1: 仕入受信から営業出庫まで（ハッピーパス、Phase B 想定）

1. 仕入元が Discord channel に在庫メッセージを投稿
2. Bot が受信 → `discord_inbound_messages` に保存（F5）
3. F3 ルール解析 → 一部 unparsed
4. F4 LLM フォールバックで残りを解決、`parse_status = parsed`
5. 担当者が `/inbound` で一覧を開き、未承認バッジ＋N 件を確認（F6）
6. レビュー画面で行ごとに採用 / 編集 → 承認
7. `inventory_movements` 追記、`products.stock_quantity` 更新（Phase B）
8. 営業が顧客問い合わせを受け、`/quotes/new` で在庫検索（F7）
9. 該当商品を選択して見積作成、PDF を送付
10. 後日、別商品を仕入元 X へ発注 → PO 作成（F8）
11. PO PDF を生成、`supplier_aliases` で X 固有表記に置換、メール送信
12. 仕入元から受領通知 → 再度 Discord 経由で受信（F5）に戻る

### UF2: マスタ運用（admin、定期メンテ）

1. admin が `/admin/masters` を開く（F2）
2. Knowledge タブで先週解析に失敗した unparsed token を確認 → rule を新規作成
3. TCG タブで先週発売の新シリーズを追加
4. Suppliers タブで新規仕入元 #46 を追加、Discord routing を設定
5. LLM 設定で当月予算超過しそうなら一時的に rule_v1_only モードに切替

### UF3: Phase 切替（admin、月次大運用）

1. admin が Phase A 状態で 1 週間並走運用を実施
2. CSV 突き合わせで CRM とスプレッドシートの差分が 0 件であることを確認
3. `/admin/phase-switch` で Phase A → B に切替（F9）
4. GS 側を読み取りビューに変更（スクリプトで自動 or 手動）
5. 2 週間 Phase B 運用、問題なければ Phase C に切替
6. 最終 CSV をエクスポート → `scripts/import_inventory_from_sheet.py` で履歴を移行

## Success Criteria

- **SC1**: tenant_006（撮影 / QA）で UF1 を Playwright で end-to-end 自動化、1 回完走で 12 ステップ全て green。
- **SC2**: 45 仕入元のうちサンプル 5 仕入元の実 raw_content（しんごさん提供）に対し、F3+F4 ハイブリッド解析の `unparsed` 件数が全体の 10% 未満。
- **SC3**: LLM 月次コストが `tenant_llm_budgets.monthly_budget_usd` 設定値の 110% 以下（hard_stop = true で 100% 以下）。
- **SC4**: Phase A 並走運用 1 週間で CRM とスプレッドシートの在庫差分が 0（手動 reconciliation 確認）。
- **SC5**: 営業 5 名がスプレッドシートを開かずに 1 週間 quote 作業を完結できる（運用観点）。
- **SC6**: 全 Sprint の Evaluator 報告で **SQLite モックではなく実 Postgres + 実 webhook ペイロード** で AC を検証している（feedback `feedback_evaluator_gap_2026_05_15.md` 反映、Coverage notes に未検証を残して PASS したケースが 0 件）。
- **SC7**: 8 Cross-feature smoke + Fresh tenant onboarding（CLAUDE.md / ADR-038）が全 Sprint で green。

## Sprint Plan

### Sprint 1: スキーマ基盤 + 既存マスタ初期投入（F1）

- **Includes**: F1
- **Definition of done**:
  - migration 047〜053 が tenant_004 / tenant_006 両方に適用済（実 Postgres で AC1.1〜1.3 確認）
  - pokemon_dex 1025 行、tcg_series_master 主要 6 シリーズ、suppliers 45 行 が seed 完了
  - ADR-034 経由で新規テナント `qa-ephemeral-f01` 作成時にも自動適用される（AC1.3）
- **Acceptance criteria covered**: AC1.1, AC1.2, AC1.3, AC1.4, AC1.5, AC1.6
- **Verification gates**: Fresh tenant onboarding 必須、Static analysis green、Blast radius #1/#2/#4 全 trigger

### Sprint 2: マスタ編集 UI（F2）

- **Includes**: F2
- **Definition of done**:
  - `/admin/masters` 4 タブが tenant_006 admin user で操作可能
  - CSV import/export がポケモン図鑑 1025 行で動作
  - i18n キー全て ja/en 同期
- **Acceptance criteria covered**: AC2.1〜2.7
- **Verification gates**: Cross-feature smoke #06 (Staff & Permissions)、Static analysis green

### Sprint 3: ルールベース解析エンジン（F3）

- **Includes**: F3
- **Definition of done**:
  - `inventory_parser.py` の単体テスト 30+ ケース pass
  - 5 仕入元 raw_content サンプルで `parse_status = parsed`
  - 解析ベンチ 1000 行 / 5 秒以内（R5 SLO 内）
- **Acceptance criteria covered**: AC3.1〜3.5
- **Verification gates**: Runtime coupling R1 (Query count)、R5 (observability)

### Sprint 4: LLM フォールバック + コスト管理（F4）

- **Includes**: F4
- **Definition of done**:
  - 実 Claude API key で 1 経路通過（tenant_006）
  - budget 超過時の hard_stop 動作確認
  - admin UI で budget 編集可能
- **Acceptance criteria covered**: AC4.1〜4.6
- **Verification gates**: External state #5 (ENV CLAUDE_API_KEY)、Runtime R5、Static analysis

### Sprint 5: Discord Bot 受信（F5）

- **Includes**: F5
- **Definition of done**:
  - 実 Discord guild に Bot を招待、`#test-inventory` から実メッセージ 3 件受信、`discord_inbound_messages` に保存（AC5.1）
  - 切断 / 再接続テスト pass（AC5.4）
  - `supplier_discord_routing` ベースのフィルタリング動作
- **Acceptance criteria covered**: AC5.1〜5.5
- **Verification gates**: External state #11 (Webhook URL)、Runtime R4 (Idempotency)、Cross-feature smoke #04 (Inbox & Channels)

### Sprint 6: 解析結果レビュー UI + 在庫差分反映（F6）

- **Includes**: F6
- **Definition of done**:
  - 担当者が `/inbound/review/{id}` で行単位の採用 / スキップ / 編集 / 差戻し
  - 承認で `inventory_movements` 行が追加され、`products.stock_quantity` が delta_qty だけ動く（Phase B 想定下のテスト）
  - 楽観ロック動作（AC6.5）
- **Acceptance criteria covered**: AC6.1〜6.7
- **Verification gates**: Runtime R2 (Concurrent smoke)、R3 (Lock probe)、Cross-feature smoke #05 (Leads & Orders) regression check

### Sprint 7: 在庫検索 UI + 見積画面連携（F7）

- **Includes**: F7
- **Definition of done**:
  - `InventorySearchBar` が QuoteCreatePage に組み込まれ、5 種類の検索キー（ja/en/expansion_code/JAN/supplier_alias）に対応
  - 検索 API レスポンス 500ms 以内（AC7.6）
  - 既存 quote 機能リグレッションなし
- **Acceptance criteria covered**: AC7.1〜7.7
- **Verification gates**: Runtime R1、R5、Cross-feature smoke #05

### Sprint 8: PO 拡張（alias 置換 + PDF + メール）（F8）

- **Includes**: F8
- **Definition of done**:
  - PDF レンダリングが alias 置換で動作（pdfminer text extract で assert）
  - メール送信が test SMTP（mailhog）にキャプチャされる
  - alias 未登録の Notes 出力（AC8.3）
- **Acceptance criteria covered**: AC8.1〜8.6
- **Verification gates**: External state #6 (API signature changes)、Static analysis

### Sprint 9: 段階的廃止 Phase A → B → C 切替（F9）

- **Includes**: F9
- **Definition of done**:
  - migration 054 適用、3 Phase の挙動切替が admin UI で操作可能
  - Phase A の CSV export と Phase C の bulk import スクリプトが完走
  - Phase 切替履歴の audit_log 記録
- **Acceptance criteria covered**: AC9.1〜9.6
- **Verification gates**: Cross-feature smoke 全 8、Fresh tenant onboarding、End-to-end SC1（UF1 完走）

## 既存資産参照サマリ（Generator が拡張ベースで実装するためのファイル一覧）

### Backend
- `astro-webapp/migrations/005_*.sql`（products, quotes, invoices）
- `astro-webapp/migrations/007_*.sql`（suppliers, purchase_orders）
- `astro-webapp/migrations/038_add_products_phase1c_columns.sql`（Phase 1-C 11 列）
- `astro-webapp/migrations/040〜045_*.sql`（meta webhook 系、idempotency / routing パターン参考）
- `astro-webapp/backend/app/routers/products.py`, `quotes.py`, `invoices.py`, `suppliers.py`, `purchase_orders.py`, `orders.py`
- `astro-webapp/backend/app/routers/webhook.py`（HMAC 検証 L268-275、`hmac.compare_digest` + `sha256=` prefix の `X-Hub-Signature-256` パターン）
- `astro-webapp/backend/app/routers/meta.py`（OAuth + idempotency 流用先）
- `astro-webapp/backend/app/auth/dependencies.py`（`require_permission` パターン）
- `astro-webapp/backend/app/discord_gateway/{client,main,config}.py`（ADR-009 M2 段階、M3 へ拡張）

### Frontend
- `astro-webapp/frontend/src/pages/ProductsPage.tsx`, `QuotesPage.tsx`, `QuoteCreatePage.tsx`, `QuoteDetailPage.tsx`, `PurchaseOrdersPage.tsx`, `SuppliersPage.tsx`, `OrdersPage.tsx`, `RolesPage.tsx`
- `astro-webapp/frontend/src/locales/ja.json`, `en.json`（ADR-027 i18n）

### Scripts / Seeds
- `astro-webapp/sheets/*.csv`（既存マスタ移行用 CSV）
- `astro-webapp/scripts/migrate_meta_*.py`（seed スクリプト構造パターン）

### 既存 ADR / Memory
- ADR-009（Discord Gateway 段階導入）
- ADR-025（deploy.yml env 注入 trap）
- ADR-026（IG message_id TEXT 化、webhook 設計パターン）
- ADR-027（i18n、`users.locale`）
- ADR-034（新規テナント migration 自動適用）
- ADR-038（Cross-feature smoke + Fresh tenant onboarding）
- Memory `feedback_evaluator_gap_2026_05_15.md`（**SQLite モック量産 PASS を避ける、実 Postgres + 実 webhook ペイロードで検証する**）

## Notes（Planner 補足）

### Migration 番号について

ブリーフでは「最新 055 前後」と記載されていたが、これは Sales Anchor（`shingo-ops/salesanchor`）の番号系統。本仕様の対象である CRM プロジェクト（`astro-webapp/migrations/`）の最新は **046**（`046_adr015_lead_foundation.sql`、2026-05-15 時点）。本仕様は **047〜054** を提案する。Generator は実装着手前に `ls astro-webapp/migrations/ | tail -5` で再確認すること。

### HMAC 署名検証について

Discord Bot は WebSocket Gateway 経由（`discord.py` 等）が主流のため、HTTP webhook の HMAC 検証は **outbound webhook を使う場合のみ** 必要。本仕様の Sprint 5 は WebSocket Gateway（既存 `discord_gateway/client.py` M2 拡張）を主経路とし、HMAC は Discord 側の Bot Token 認証で代替する。ただし将来 Discord Webhook（HTTP）を追加する場合は、`backend/app/routers/webhook.py` L268-275 と同型の `X-Hub-Signature-256` + `hmac.compare_digest` パターンを `discord_webhook_idempotency` と組み合わせて実装する。

### SQLite モック禁止条項

過去スプリント（Sprint 2/3/4 系の一部）で SQLite + AsgiTransport を「動作確認」として PASS した結果、本番（PostgreSQL）固有のパス（schema-prefixed query、JSONB index、PARTIAL UNIQUE INDEX、search_path）で複数欠陥が露呈した（`feedback_evaluator_gap_2026_05_15.md`）。

本仕様の **すべての Sprint で**:
- 解析エンジンの単体テスト → SQLite + フィクスチャ OK
- マルチテナント分離、HMAC 検証、JSONB クエリ、migration 適用、search_path 切替 → **必ず VPS の PostgreSQL（tenant_006）に対して実行**
- Discord 受信、Claude API、メール送信 → **モックではなく実 endpoint で 1 経路通す**
- Coverage notes に「Sprint N+1 持ち越し」「mock のみ」「ライブサーバー未起動」を理由に未検証を残したら、その AC は最大 3/5（自動 FAIL）

### i18n / ハードコード日本語の処理

すべての新規 UI 文言は `t("inventory.*")`, `t("admin.masters.*")`, `t("inbound.review.*")`, `t("purchase_orders.alias.*")` 等の名前空間で ja.json / en.json に同一キーを追加。Generator は PR 前に以下を実行:

```bash
git diff --name-only develop...HEAD -- 'astro-webapp/frontend/src/**/*.tsx' 'astro-webapp/frontend/src/**/*.ts' \
  | grep -v 'locales/' \
  | xargs -I{} grep -nE '[ぁ-んァ-ヶ一-龯]' {} 2>/dev/null
```

ヒット 0 を確認。

### マルチテナント migration 適用

migration 047〜054 はすべて `_TENANT_TABLES_SQL` テンプレート（`backend/app/services/tenant.py`）にも反映が必要。ADR-034 が main マージ前は手動で template 更新 + 既存全テナント / 新規テナント両方への適用経路を Generator が説明、Evaluator が実機確認。`public.pokemon_dex` / `public.trainer_dex` / `public.tcg_series_master` は **共有マスタ** のため `public` schema 配置で全テナント共有（Q6 確定後にスコープ最終確定）。

### Verification（Planner Self-check）

- [x] 全 Sprint に Playwright 検証可能な AC が書かれている
- [x] 既存ファイルパスへの言及がある（新規実装ではなく拡張になっている）
- [x] migration 番号が既存と衝突しない（最新 046 + 1 〜 054 を提案、Notes に注記）
- [x] Discord webhook の HMAC 署名検証パターンが Meta webhook 流用と明記（Notes 節）
- [x] `supplier_aliases` の i18n 対応（language 列）が含まれる（F1, migration 047）
- [x] 段階的廃止の Phase A/B/C 切替手順が運用可能なレベルで書かれている（F9, UF3, AC9.x）
- [x] 未解決事項が Q1〜Q6 として末尾に列挙されている（下記）

---

## 未解決事項（ひとしさん／しんごさんへの問い）

### Q1: 解析結果の承認フロー — 全件承認 vs 信頼スコア閾値運用

F4 LLM フォールバックは `confidence` を返せる。F3 ルールも alias 完全一致なら confidence=1.0、部分一致は 0.5〜0.9 程度で設定可能。

- 案 A: **全件人手承認**（confidence 問わず必ず F6 レビュー必須）
- 案 B: **閾値運用**（confidence >= 0.95 は自動承認、< 0.95 のみ人手レビュー）
- 案 C: **仕入元別運用**（信頼ある仕入元 #X は自動、新規 #Y は手動）

→ 運用負荷とリスク（誤反映時のロールバック手間）のトレードオフ。**初期実装は案 A、Sprint 6 以降の運用観察後に案 B / C へ移行で OK か？**

### Q2: LLM コスト上限超過時の挙動

`tenant_llm_budgets.hard_stop` フラグの挙動を確定したい。

- 案 A: **hard_stop=true**: 上限超過後は rule_v1 のみで処理、unparsed は次月へ持ち越し（メッセージは保存）
- 案 B: **hard_stop=false**: 上限超過後も LLM 続行、admin に warning 通知のみ
- 案 C: **段階的**: 80% 警告、100% 警告強化、120% 強制停止

→ **初期実装は案 A（hard_stop=true 強制）+ admin 通知（Discord webhook）で OK か？** 月次予算の初期値は **どの程度** が現実的か（5 USD / 20 USD / 50 USD ）？

### Q3: 在庫移動履歴（inventory_movements）の保持世代

`inventory_movements` は append-only。45 仕入元 × 月数十件 × 数年 想定で行数は累積する。

- 案 A: **全件永久保持**（GDPR / 顧客データではないので保持自体は問題なし）
- 案 B: **n ヶ月でアーカイブ**（既存 `data_deletion_logs` migration 039 と整合）
- 案 C: **物理削除なし、論理削除 + パーティショニング**

→ **初期実装は案 A（全件永久）+ 半年後にパーティショニング検討で OK か？**

### Q4: 仕入元マスタの個人 / 法人混在

現状 45 仕入元のうち、個人名（LINE 名 / Discord ID 直）と法人名（株式会社…）が混在。`suppliers` テーブルは現在 1 種類のみ。

- 案 A: **type 列追加**（`supplier_type ENUM('individual', 'corporate')`、PO の宛名表記が変わる）
- 案 B: **既存 1 種類のまま運用**（個人名も法人名同様に name 列に入れる）
- 案 C: **`companies` / `contacts` 階層と同様の階層化**（Phase 1-B-2 の知見流用）

→ **PO PDF の宛名 / 敬称（御中 / 様）を自動で出し分ける必要があれば案 A、特に不要なら案 B で良いか？** 案 C は将来拡張の余地として残す？

### Q5: 営業の在庫検索の検索式

F7 の `InventorySearchBar` の検索キーをどこまで横断するか確定したい。

- ja: products.name + pokemon_dex.name_ja + trainer_dex.name_ja
- en: products.name_en + pokemon_dex.name_en + trainer_dex.name_en
- expansion_code（products.expansion_code）
- card_number（products.card_number）
- JAN（products.jan_code）
- supplier_alias（supplier_aliases.alias_text）
- tcg_series_master.name_ja / name_en

→ **初期実装で全 7 種横断 + AND/OR を明示的に切替できる UI でよいか？** それとも単一フリーテキストで「ヒットすればよい」OR 検索のみで十分か？ レスポンス時間 500ms 制約と要相談。

### Q6: マルチテナント時の knowledge / aliases スコープ

`knowledge_rules` / `supplier_aliases` をテナント間で共有するか分離するか。

- 案 A: **完全テナント分離**（各テナントが自分の knowledge を持つ、横展開不可）
- 案 B: **public 共有 + テナント上書き**（base は public、テナントごとに上書きや追加可）
- 案 C: **テナント分離 + admin import**（admin が他テナントから CSV エクスポート / インポート手動移植）

→ 現状 tenant_004 一本運用なので緊急性は低いが、将来 SaaS 化時に直結する判断。**初期実装は案 A（完全分離）で、Q3 と同じく将来 ADR で見直す前提で OK か？** 共有マスタ（pokemon_dex / trainer_dex / tcg_series_master）は public schema で確定で良いか？

---

## Audit notes（Mode A 起案、外部仕様 audit ではない）

本仕様は brief `~/.claude/plans/synchronous-wishing-sun.md` を Mode A（短い idea → 完全仕様）として展開したもの。Mode B（外部仕様 audit）ではないため audit rubric は適用せず。前 spec.md（Sales Anchor / shingo-ops の ADR-021 Sprint 5）は別件のため `spec-prev-adr021-sprint5.md` に退避し、本ファイルでフル書き換え。
