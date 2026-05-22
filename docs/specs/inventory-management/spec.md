# Jarvis CRM 在庫管理機能整備（仕入受信〜営業フロー連鎖）

> 注: このリポジトリの直前 `spec.md` は ADR-021 Sprint 5（Sales Anchor / shingo-ops）の起案で、本仕様とは別件。前版は `.claude-pipeline/spec-prev-adr021-sprint5.md` に退避済み。v1.0 の起案版は `.claude-pipeline/spec-v1.0.md` に保管。

## Version

- **v1.2** (2026-05-22): **Phase A 並走長期化方針確定**（ひとしさん × しんごさん協議）。spec の F9 / UF3 / Sprint 9 を「段階的廃止 Phase A → B → C 切替」から「Phase A 並走運用整備」に絞り、Phase B / C（書込切替・スプレッドシート閉鎖）は Out-of-scope へ移動。Sprint 1-8 develop merged 後（PR #507-522）、Sprint 9 はこの絞り込み版で着手。
- **v1.1** (2026-05-21): Q1〜Q6 確定値反映。Q6 で **マーケットプレイス型マルチテナント設計** が確定し、在庫・商品マスタ・仕入元・正規化辞書を中央 `public` schema 共有に変更。LLM プロバイダを Claude → Gemini 2.5 Flash に変更（既存運用に整合）。Q4 確定で `suppliers.supplier_type` 列追加。F1 / F2 / F4 / F6 / F7 / F8 / Notes / Q セクションを更新、Out-of-scope セクション新設。
- **v1.0** (2026-05-21): 初版起案、Q1〜Q6 未解決として末尾列挙。

## Overview

Jarvis CRM（HIGH LIFE JPN / Treasure Island JP の B2B SaaS CRM、本番テナント `tenant_004 / highlife-jpn`）は Phase 1〜2 で商品・顧客・見積・請求・発注の基本 CRUD と Phase 1-C M-MVP で TCG B2B 輸出向けの 11 列拡張（migration 038、`jan_code/card_number/expansion_code/rarity/language/unit_price_usd|eur/image_url/is_archived/archived_at/supplier_default_id`）まで完了している。一方、現場の在庫運用は依然として Google スプレッドシート（45 仕入元、複数 TCG マスタ、API 解析シート、正規化在庫リスト）に依存しており、Discord で届く仕入元メッセージの正規化〜在庫反映〜営業活動への連携が CRM に取り込まれていない。

本スプリント群は、この **Discord 受信 → 正規化解析（ルール＋LLM ハイブリッド）→ 担当者承認 → 在庫反映 → 営業（在庫検索・見積・発注書）連携** の一気通貫を CRM 側に実装し、スプレッドシートとは **Phase A（並走）を当面長期継続**する（v1.2 で確定、Phase B/C 切替は時期未定で別 ADR）。新規実装ではなく、既存資産（`backend/migrations/005|007|038`、`discord_gateway/` M2 段階、Meta webhook HMAC 検証パターン、`ProductsPage/QuotesPage/QuoteCreatePage/PurchaseOrdersPage/SuppliersPage` などの React ページ、Phase 1 の `require_permission()` パターン、ADR-027 i18n、ADR-034 で整備中の新規テナント migration 自動適用）をすべて拡張ベースで活用する。

対象ユーザーは admin（マスタ編集・解析結果承認・PO 発行）、サポート / 営業（在庫検索・見積・問い合わせ応答）、観測者（読み取り）。45 仕入元には個人名・法人名が混在し、商品マスタは現状ポケモン・トレーナー図鑑（合計 1025+α）と Pokemon Booster Box / One Piece / Dragon Ball / Union Arena / 遊戯王 のシリーズマスタを横断する。

## Goals

- **G1**: 仕入元 Discord メッセージを 1 メッセージ＝1 件単位で受信・保存・正規化し、担当者が確認・承認すると `products` の在庫数・参考価格・状態が更新される。
- **G2**: 45 仕入元それぞれの言い回しを `supplier_aliases` で学習し、PO（発注書）PDF / メール送信時に該当仕入元固有の表記へ自動置換できる。
- **G3**: 営業がスプレッドシートを開かず、CRM 内の在庫検索 → 見積作成 → 顧客送付までを一気通貫で完了できる。
- **G4**: 解析は **ルール＋辞書優先・失敗時のみ Gemini 2.5 Flash フォールバック** のハイブリッドで、テナント月次 LLM コスト上限を設定可能（A2 確定: hard_stop=true）。
- **G5**: **Phase A（並走）を当面長期運用形態**として整備し、スプレッドシート併用期間中も整合を保つ（v1.2 確定、Phase B/C 切替は CRM 軌道に乗ってから別 ADR で判断）。

## Non-Goals

- スプレッドシートからの全自動同期 API ブリッジ（読み取り専用の CSV エクスポートで対応、双方向同期は対象外）。
- TCG 価格情報の外部ソース自動取得（USD/EUR の自動同期、TCGPlayer 等の API 連携）。
- 在庫の物理ロケーション管理（倉庫棚位置、ロット管理）。
- 仕入元との Discord 上での自動返信ボット（Bot は受信専用、能動応答は本スプリント群対象外）。
- LLM プロバイダーの抽象化レイヤー（Gemini 2.5 Flash 固定で実装、別プロバイダー対応は別 ADR）。
- 既存 ADR-034（新規テナント migration 自動適用）の代替実装。本仕様の migration はすべて ADR-034 経由で適用される前提。

## User Personas

- **Admin（しんごさん）**: マスタ編集、解析失敗のレビュー、承認フロー閾値変更、LLM コスト上限設定、Phase 切替を担当。`master.*.edit` 系権限保持。
- **サポート/営業担当**: 在庫検索、見積作成、顧客問い合わせ応答、解析結果の確認・承認（admin 委任時）。`inventory.view`, `quotes.create`, `parse_review.approve` 保持。
- **仕入担当**: PO 起票、仕入元別 alias の補正、解析結果の差分確認。`purchase_orders.create`, `supplier_aliases.edit`。
- **観測者（経理 / 役員）**: 読み取り専用で在庫・売上・PO の状態を閲覧。

## Features

### F1: スキーマ基盤と既存マスタ初期投入（マーケットプレイス型）

- **Description**: 在庫パイプラインのデータ基盤を migration バンドル（047〜054）で導入する。**マーケットプレイス型設計（A6 確定）に基づき、在庫・商品マスタ・仕入元・正規化辞書は `public` schema に配置し全テナント共有**。`tenant_id` カラムを持つのは「テナント別の操作履歴」のみ。Phase 1-C 038 と衝突しないよう products は拡張のみ（列追加 / インデックス追加）に留めるが、**スキーマは `public` に移管**（既存 `tenant_004` の products を Phase C で `public.products` へ data migration、F9 で詳細化）。
- **既存資産参照**:
  - `astro-webapp/migrations/005_*.sql`（products, quotes, invoices）
  - `astro-webapp/migrations/007_*.sql`（suppliers, purchase_orders）
  - `astro-webapp/migrations/038_add_products_phase1c_columns.sql`
  - `astro-webapp/migrations/044_create_meta_page_routing_trigger.sql`（マルチテナント trigger 参考）

- **新規 migration（提案番号、最新 046 の次から、ADR-034 適用順を維持）**:

  #### `public` schema（全テナント共有、Jarvis 運用 admin のみ書き込み）
  - `047_add_suppliers_type_and_promote_public.sql` — `suppliers.supplier_type ENUM('individual', 'corporate')` 追加（A4 確定）。既存 `{tenant_xxx}.suppliers` を `public.suppliers` に移管する DDL を含む（F9 Phase C と整合、テナント schema からは VIEW で参照可能に）
  - `048_create_supplier_aliases.sql` — `public.supplier_aliases (id, product_id, supplier_id, alias_text, language CHAR(2) DEFAULT 'ja', confidence NUMERIC(4,3), source TEXT, created_by, created_at, updated_at, UNIQUE(supplier_id, alias_text, language))` ← **`tenant_id` 列なし**（中央共有）
  - `049_create_knowledge_rules.sql` — `public.knowledge_rules (id, category, pattern_type, pattern, normalized_to, priority INT, language CHAR(2), is_active BOOLEAN, created_by, created_at)` ← **`tenant_id` 列なし**
  - `050_create_discord_inbound_messages.sql` — `public.discord_inbound_messages (id, supplier_id, discord_channel_id, discord_message_id, raw_content, received_at, parse_status, parse_engine, parse_result_json JSONB, exclude_reason, operator_comment, llm_cost_usd NUMERIC(8,4), UNIQUE(discord_message_id))` ← **`tenant_id` 列なし**（受信は中央経由）
  - `051_create_supplier_discord_routing.sql` — `public.supplier_discord_routing (id, supplier_id, discord_guild_id, discord_channel_id, is_active, UNIQUE(discord_guild_id, discord_channel_id))`
  - `052_create_tcg_and_dex_masters.sql` — `public.pokemon_dex(id, dex_number, name_ja, name_en, generation, region)`, `public.trainer_dex(id, dex_number, name_ja, name_en, era)`, `public.tcg_series_master(id, tcg_type, series_code, name_ja, name_en, release_date, category)`
  - `053_create_inventory_movements_and_budget.sql` — `public.inventory_movements (id, tenant_id, product_id, delta_qty, before_qty, after_qty, source_type, source_id, supplier_id, operator_id, occurred_at, notes)` ← **`tenant_id` 列あり**（どのテナントの操作で動いたかの追跡用）、`public.tenant_llm_budgets (tenant_id PK, monthly_budget_usd, current_month_usd, last_reset_at, hard_stop BOOLEAN DEFAULT true)`、`public.discord_webhook_idempotency` テーブル

  #### `{tenant_xxx}` schema（テナント別、既存通り）
  - `054_tenant_rbac_extensions.sql` — `{tenant_xxx}.role_permissions` に `inventory.visibility.*` キー追加（テナント admin が自社内ロールで「在庫を誰に見せるか」を絞れる権限）。`{tenant_xxx}.purchase_orders` は既存テーブル拡張（F8 でテナント名義出力用に `company_name_snapshot, contact_info_snapshot` 列を追加）

- **マスタ初期投入スクリプト**: `scripts/seed_pokemon_dex.py`, `scripts/seed_tcg_series.py`, `scripts/seed_suppliers_from_sheet.py`（**`public` schema 向け、tenant_id なし**、CSV 入力、冪等、`scripts/migrate_meta_*` のスクリプト構造踏襲）
- **User stories**:
  - 「Jarvis 運用 admin として、新規テナントを作るとき在庫管理に必要な `public` スキーマと `{tenant_xxx}` 拡張がすべて自動で適用されてほしい（ADR-034 経由）」
  - 「テナント admin として、自社内のロール（営業 / 経理 / 観測者）に対し『在庫を見せる / 見せない』を設定したい」
- **Acceptance criteria**:
  - **AC1.1**: PostgreSQL（VPS の `tenant_004` および `tenant_006` 環境）に対し、migration 047〜054 を順序適用後、`SELECT table_schema, table_name FROM information_schema.tables WHERE table_schema IN ('public', 'tenant_004', 'tenant_006')` で配置どおりのテーブル群が存在することを確認（SQLite モックではなく実 Postgres で）。
  - **AC1.2**: `public.supplier_aliases` に `(supplier_id, alias_text, 'ja')` の重複 INSERT を試行すると UNIQUE 制約で 23505 が返る。
  - **AC1.3**: 新規テナント `qa-ephemeral-fNN` を `scripts/qa/create-fresh-tenant.sh` で作成し、`public` テーブルは共有のまま、`{tenant_qa-ephemeral-fNN}` には migration 054 の RBAC 拡張のみが適用されることを diff で確認。
  - **AC1.4**: `scripts/seed_pokemon_dex.py --dry-run` で 1025 行の検証ログ、`--apply` で `public.pokemon_dex` に 1025 行が挿入される。二度実行しても件数は変わらない（冪等）。
  - **AC1.5**: Playwright が backend `/api/v1/admin/migrations/status` を叩いて 047〜054 すべて applied=true を確認するスモークシナリオが green。
  - **AC1.6**: `public.discord_webhook_idempotency` の構造は既存 `{tenant_xxx}.meta_webhook_idempotency`（migration 040 系）と一致しており、Reviewer agent が diff で確認できる。
  - **AC1.7**: `public.suppliers` には `supplier_type` 列が存在し、INSERT に `'individual'` / `'corporate'` 以外を指定すると CHECK 制約で 23514 が返る（A4 確定）。
  - **AC1.8**: `{tenant_xxx}.role_permissions` に `inventory.visibility.staff`, `inventory.visibility.viewer` などのキーが seed されている（テナント admin が UI で割当可能）。

### F2: マスタ編集 UI（権限二層: 中央 admin + テナント admin）

- **Description**: マーケットプレイス型に合わせて UI を **二層構造** にする:
  - **`/super-admin/masters`** (Jarvis 運用 admin 専用、`is_super_admin = true` のみ): 4 タブで中央マスタの全 CRUD
  - **`/admin/inventory-visibility`** (各テナント admin): 自社内ロールに対する在庫閲覧権限の設定のみ
- **既存資産参照**:
  - `astro-webapp/frontend/src/pages/SuppliersPage.tsx`（仕入元 CRUD ベース）
  - `astro-webapp/frontend/src/pages/RolesPage.tsx`（テナント admin ロール管理パターン）
  - `astro-webapp/backend/app/auth/dependencies.py`（`require_permission` パターン）
  - `astro-webapp/frontend/src/locales/ja.json`, `en.json`（i18n キー）
- **新規 UI 構造**:
  #### 中央 admin（Jarvis 運用、Hitoshi さん／しんごさん）
  - `pages/super-admin/MastersPage.tsx`（タブコンテナ、`require_super_admin` ガード）
  - `pages/super-admin/KnowledgeAliasesTab.tsx`（`public.knowledge_rules` + `public.supplier_aliases` の全文検索＋一括 CSV import/export、行編集）
  - `pages/super-admin/TcgSeriesTab.tsx`（`public.tcg_series_master`、5 TCG タイプの select + テーブル）
  - `pages/super-admin/DexTab.tsx`（`public.pokemon_dex` / `public.trainer_dex` 切替）
  - `pages/super-admin/SuppliersAdminTab.tsx`（`public.suppliers` 拡張 + `public.supplier_discord_routing` 紐付け UI、`supplier_type` 選択）

  #### テナント admin
  - `pages/admin/InventoryVisibilityPage.tsx`（各ロールに対し `inventory.visibility.*` 権限を ON/OFF）
- **権限キー**:
  - 中央: `central.knowledge.edit`, `central.aliases.edit`, `central.tcg.edit`, `central.dex.edit`, `central.supplier.edit`（`is_super_admin` user のみに付与）
  - テナント: `tenant.inventory_visibility.edit`（各テナント admin に付与、配下ロールの `inventory.visibility.staff` / `inventory.visibility.viewer` / `inventory.visibility.full` 等を割当）
- **User stories**:
  - 「Jarvis 運用 admin として、新しい仕入元が独特な略語を使い始めたら `public.knowledge_rules` に追加して以後の解析に反映したい」
  - 「Jarvis 運用 admin として、CSV で図鑑を一括差し替えしたい（ポケモン公式が新作を出したとき）」
  - 「テナント A の admin として、自社の経理ロールには在庫数を見せたくない（個別単価は OK だが数量は隠す）」
- **Acceptance criteria**:
  - **AC2.1**: Playwright が `/super-admin/masters` にアクセスし、`is_super_admin = false` ユーザーで開くと 403、`is_super_admin = true` で開くと 4 タブが表示される（実 backend、tenant_006 admin と運用 super-admin の 2 ロールで検証）。
  - **AC2.2**: Knowledge タブで新規 rule（pattern_type=regex, pattern=`^PSV1a-(\d+)`, normalized_to=`SV1a-$1`, language=ja）を作成 → 保存 → 一覧に表示 → `public.knowledge_rules` に行が存在することを SQL で確認できる。
  - **AC2.3**: TCG タブで Pokemon Booster Box の `SV1a` 行を編集 → 保存 → `public.tcg_series_master` に反映、ja/en 両方の表示が i18n キー経由で切り替わる。
  - **AC2.4**: Dex タブでポケモン #25 の英名を編集して保存 → `public.pokemon_dex` 更新 → 再読み込みで反映。
  - **AC2.5**: Suppliers タブで仕入元 #3 に Discord guild_id / channel_id を割り当て → `public.supplier_discord_routing` に行が追加され、`is_active = true` で保存される。`supplier_type` を `corporate` / `individual` で切替できる。
  - **AC2.6**: CSV import: 不正フォーマット（必須列欠落）の CSV をアップロード → エラーメッセージが i18n キー経由で表示、DB は変化なし。正常 CSV では行数差分が表示され、確認後 commit される。
  - **AC2.7**: i18n grep: `git diff frontend/src/pages/super-admin/ frontend/src/pages/admin/InventoryVisibilityPage.tsx` で日本語ハードコード残骸 0 件、`ja.json/en.json` に同一キーが存在する。
  - **AC2.8**: `/admin/inventory-visibility`（テナント admin） で「経理」ロールの `inventory.visibility.full` を OFF にすると、経理ロールのユーザーが在庫検索 UI に入っても在庫数列が `***` 表示になる（F7 連携）。

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

### F4: LLM フォールバック（Gemini 2.5 Flash）と コスト管理

- **Description**: F3 が `unparsed` を返した行のみ **Gemini 2.5 Flash** へフォールバックする（A2 確定、Claude API ではない）。プロンプトには raw_content + `public.knowledge_rules` スナップショット + 出力スキーマ（Gemini structured output / JSON schema 強制）を含める。コストは `public.tenant_llm_budgets` で月次集計し、`hard_stop = true`（デフォルト）で上限超過時は fallback を停止して `parse_status = budget_exhausted` を記録。
- **既存資産参照**:
  - `astro-webapp/backend/app/services/` 配下に既存 Gemini 呼び出しがあれば流用（既存運用で Gemini 2.5 Flash を使っている既存コンポーネントの SDK / 鍵管理を引き継ぐ）
- **新規ファイル**:
  - `backend/app/services/inventory_parser_llm.py`（Gemini クライアント呼び出し + structured output）
  - `backend/app/services/llm_budget.py`（`public.tenant_llm_budgets` の current_month_usd 集計）
- **環境変数**: `GEMINI_API_KEY`（既存 secret 体系、deploy.yml の sed 追加方式に従う、ADR-025 trap 回避）
- **モデル選定根拠**: Gemini 2.5 Flash は (i) 日本語精度が在庫メッセージの構造化抽出に十分、(ii) コスト効率が Claude Sonnet / Opus より大幅優位、(iii) 既存 Jarvis CRM の他コンポーネントで運用実績あり、の 3 点。別モデル採用は別 ADR で正当化（memory: `project_jarvis_llm_gemini.md`）。
- **Acceptance criteria**:
  - **AC4.1**: F3 で unparsed が 1 行以上ある raw_content を流す → Gemini 2.5 Flash を 1 回呼ぶ → `parse_result_json` に LLM 由来 items がマージされる。tenant_006 で実 API key を使って 1 経路通す（モックではなく）。
  - **AC4.2**: `public.discord_inbound_messages.llm_cost_usd` に Gemini API 応答の usage（input/output token 数）から算出した実コストが記録される（料金表は Gemini 2.5 Flash の最新公式値、ハードコード許容、別 ADR で外出し検討）。
  - **AC4.3**: `public.tenant_llm_budgets.monthly_budget_usd = 0.01` に設定し、超過するまで 5 件流す → 超過後の 1 件は `parse_status = budget_exhausted, parse_engine = rule_v1_fallback_blocked` で API 呼び出しなし。admin への Discord webhook 通知が 1 回飛ぶ（A2 確定）。
  - **AC4.4**: 月初の `last_reset_at` が変わると `current_month_usd` が 0 にリセットされる（cron or 起動時 check）。
  - **AC4.5**: API キー欠落 / 不正時の挙動: rule_v1 のみで処理し、parse_status = `parsed_rule_only` で記録、500 エラーにしない。
  - **AC4.6**: Playwright で Jarvis 運用 admin が `/super-admin/masters` → LLM 設定タブ（5 タブ目）から budget を編集 → `public.tenant_llm_budgets` 即時反映される。テナント admin ではこの UI に到達できない（403）。

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

### F6: 解析結果レビュー UI と在庫差分反映（中央 admin 承認）

- **Description**: 解析済 `public.discord_inbound_messages` の `parse_result_json` を **Jarvis 運用 admin（中央）が UI でレビュー** → 商品ごとに「採用 / スキップ / 編集」操作 → 承認すると `public.inventory_movements` に行を追加し、`public.products.stock_quantity` を更新する。A1 確定により **全件人手承認**（自動承認パスは v1.1 では実装しない）。テナント側ユーザーは review 結果（=反映後の products テーブル）のみ参照可能で、レビュー UI へのアクセスはなし。
- **既存資産参照**:
  - `astro-webapp/frontend/src/pages/SuppliersPage.tsx`（一覧 UI パターン）
  - `astro-webapp/backend/app/routers/products.py`（products 更新エンドポイント、`public` スキーマ向けに拡張）
- **新規ファイル**:
  - `frontend/src/pages/super-admin/DiscordInboundPage.tsx`（一覧、`is_super_admin` ガード）
  - `frontend/src/pages/super-admin/ParseReviewPage.tsx`（レビュー、`is_super_admin` ガード）
  - `backend/app/routers/parse_review.py`（`require_super_admin` デコレータ）
- **権限**: `central.parse_review.approve`, `central.parse_review.reject`（Jarvis 運用 admin のみ）
- **Acceptance criteria**:
  - **AC6.1**: Playwright が `is_super_admin` user で「未承認」フィルタを開き、1 件選んで行ごとの採用 / スキップを操作 → 承認 → `public.inventory_movements` に該当行数の INSERT、`public.products.stock_quantity` が delta_qty だけ増減。
  - **AC6.2**: 承認後、`public.discord_inbound_messages.parse_status = approved`、`operator_comment` に reviewer の任意メモが入る。`operator_id` は Jarvis 運用 admin の user_id。
  - **AC6.3**: スキップした行は `parse_result_json.skipped[]` に保存され、再 review 時に履歴として参照できる。
  - **AC6.4**: 差し戻し（reject）操作で `parse_status = rejected` + `exclude_reason` 必須記録、`public.products` 無変化。
  - **AC6.5**: 同一メッセージを別 admin が同時に承認しようとすると後勝ち禁止（楽観ロック or 409 conflict）。
  - **AC6.6**: 在庫差分は `public.inventory_movements` の append-only 形式で保持され、`public.products.stock_quantity` の現値と `SUM(delta_qty) over inventory_movements WHERE product_id = X` が常に一致（DB 制約 or assertion）。
  - **AC6.7**: i18n: レビュー画面のすべての UI 文言が `t("inbound.review.*")` 経由、ja/en 同期。
  - **AC6.8**: テナント admin / 一般ユーザーが `/super-admin/inbound` 系 URL に直接アクセスすると 403、サイドバーにもリンクが表示されない。

### F7: 営業向け在庫検索 UI と見積画面連携（全 7 種横断 + AND/OR）

- **Description**: 営業画面に在庫検索を追加。A5 確定により以下 **7 種すべてを横断検索**:
  1. ja: `public.products.name` + `public.pokemon_dex.name_ja` + `public.trainer_dex.name_ja`
  2. en: `public.products.name_en` + `public.pokemon_dex.name_en` + `public.trainer_dex.name_en`
  3. `public.products.expansion_code`
  4. `public.products.card_number`
  5. `public.products.jan_code`
  6. `public.supplier_aliases.alias_text`
  7. `public.tcg_series_master.name_ja` / `name_en`

  検索 UI には **AND/OR トグル**（複数キーワード入力時の挙動切替）を配置。検索 API は **`public` schema 検索 + テナント側 `inventory.visibility.*` 権限フィルタ** の 2 段構え。既存 `QuoteCreatePage.tsx` の商品選択をこの検索 component に置換し、選択時は商品の標準名（`public.products.name`）で見積行に乗せる。

- **既存資産参照**:
  - `astro-webapp/frontend/src/pages/QuoteCreatePage.tsx`
  - `astro-webapp/frontend/src/pages/QuoteDetailPage.tsx`
  - `astro-webapp/backend/app/routers/products.py`（既存検索エンドポイント、`public.products` 向けに拡張）
- **新規ファイル**:
  - `frontend/src/components/InventorySearchBar.tsx`（AND/OR トグル付き）
  - `backend/app/routers/inventory_search.py`（`GET /inventory/search?q=...&lang=...&op=and|or`、ロール権限フィルタ）
- **Acceptance criteria**:
  - **AC7.1**: Playwright で営業 user として `/quotes/new` を開き、検索バーに「リザードン」と入力 → 候補に日本語名一致 + 英名 Charizard が含まれる（`public.pokemon_dex` 横断）。
  - **AC7.2**: 検索バーに `SV1a-001` を入力 → 該当 `card_number` の product が候補トップに来る。
  - **AC7.3**: 検索バーに supplier alias「リザ eX SAR」を入力 → `public.supplier_aliases` 解決経由で標準名 product が候補に出る。
  - **AC7.4**: 候補から 1 件を選択 → quote_items に標準名 + 標準 unit_price で行追加。
  - **AC7.5**: 在庫 0 商品は候補末尾 / グレーアウト表示で、選択時に警告（既存 toast パターン）。
  - **AC7.6**: 検索 API レスポンス時間: tenant_006 seed (5 products) で 200ms 以内 / tenant_004 本番見立て (1000 products 想定) で **500ms 以内**（A5 SLO、計測は p95）。
  - **AC7.7**: i18n: 検索 placeholder, 警告メッセージ, AND/OR トグルラベルすべて `t()` 経由。
  - **AC7.8**: AND モードで「リザードン SV1a」を入力 → 「リザードン」と「SV1a」両方ヒットする商品のみ。OR モードで同じクエリ → どちらか一方でもヒットする商品が表示される（実 Postgres tenant_006 で検証、件数 assert）。
  - **AC7.9**: テナント A の経理ロールで `inventory.visibility.full = false` の場合、検索結果から在庫数列が `***` でマスクされる（F2 連携、AC2.8 と整合）。

### F8: PO（発注書）拡張 — テナント名義出力 + aliases 置換 + PDF + メール

- **Description**: 既存 `PurchaseOrdersPage.tsx` を拡張。**各テナント（セラー）名義で仕入元に発注する**（A6 確定）。PDF / メールには:
  - 宛先（仕入元）: `public.suppliers.supplier_type` により「{name} 御中」（corporate）/「{name} 様」（individual）の敬称を自動付与（A4 確定）
  - 差出人（セラー）: 各テナントの会社名・印鑑・連絡先（`{tenant_xxx}.tenant_profile` 等の既存源泉 / なければ新規）
  - 商品名: 内部表示は標準名、PDF / メール送信時のみ `public.supplier_aliases` から該当仕入元の `alias_text` に自動置換

  PDF は既存 invoice の PDF パイプライン流用、メールは既存 SMTP（無ければ新規 ADR 起案を Q として明記）。
- **既存資産参照**:
  - `astro-webapp/frontend/src/pages/PurchaseOrdersPage.tsx`
  - `astro-webapp/backend/app/routers/purchase_orders.py`
  - `astro-webapp/backend/app/services/`（既存 PDF 生成、invoices.py 系の PDF 機能）
  - `{tenant_xxx}.tenant_profile`（会社名・印鑑画像・連絡先、既存 or 新規 migration 054 で導入検討）
- **新規ファイル**:
  - `backend/app/services/po_renderer.py`（テナント名義レンダリング + alias 置換 + 敬称分岐）
  - `backend/app/services/po_mailer.py`
- **Acceptance criteria**:
  - **AC8.1**: PO 詳細画面で「PDF ダウンロード」を押す → ブラウザがダウンロードしたファイルを Playwright が受信 → PDF 内の商品名が `public.supplier_aliases.alias_text`（該当仕入元の言い回し）に置換されている（pdfminer で text extract して assert）。
  - **AC8.2**: 「メール送信」を押す → 仕入元の email 宛に PDF 添付メールが送信される（テスト環境では mailtrap / mailhog にキャプチャ）→ 件名 / 本文に標準名が含まれず alias_text のみ含まれる。
  - **AC8.3**: 該当仕入元に alias 未登録の商品は標準名のままレンダリングされ、PDF 末尾の「Notes」欄に「alias 未登録: <product_name>」が列挙される。
  - **AC8.4**: alias が ja/en 両方ある場合は仕入元の `default_language` に従う（`public.suppliers.default_language` 列追加、migration 047 に同梱）。
  - **AC8.5**: メール送信失敗時は PO ステータスが `sent` にならず、`error` で記録、再送ボタンが表示される。
  - **AC8.6**: 既存 PO の一覧 / 編集機能はリグレッションなし（Playwright e2e で確認）。
  - **AC8.7**: テナント A のセラー名義で PDF を出力 → 差出人欄にテナント A の会社名・住所・連絡先が表示される（`{tenant_A}.tenant_profile` 由来、tenant_006 で検証）。
  - **AC8.8**: 仕入元 `supplier_type='corporate'` → PDF 宛名「{name} 御中」、`'individual'` → 「{name} 様」が出力される（A4 連携、両ケースを Playwright で検証）。

### F9: Phase A 並走運用整備（v1.2 で範囲縮小）

- **Description**: **Phase A（スプレッドシート並走）を長期運用形態**として整備する（v1.2 確定）。CRM 側で Discord 在庫受信・解析・承認・差分表示まで実装するが、**`products.stock_quantity` の真値はスプレッドシート側**で維持し、CRM 側は記録・表示のみ。スプレッドシートとの整合を保つための CSV エクスポート・差分監視・運用 admin UI を提供する。
- **Phase B（書込切替）/ Phase C（スプレッドシート閉鎖）は時期未定で本仕様 Out-of-scope**。CRM が軌道に乗り、しんごさん／ひとしさんが切替判断するタイミングで別 ADR を起案する。
- **既存資産参照**:
  - `astro-webapp/migrations/040_create_tenant_meta_config.sql`（tenant_settings 系の先例）
  - Sprint 6 で導入済 `public.inventory_movements`（承認履歴は既に append-only で保持）
- **Phase 定義**:
  - **Phase A（並走、本仕様の対象）**: CRM 側で受信・解析・表示まで実装、`products.stock_quantity` の真値はスプレッドシート側、CRM は記録＋表示のみ。承認操作は `inventory_movements` に記録するが `products.stock_quantity` には反映しない（warning toast 表示）。スプレッドシートへの差分は CSV エクスポート（手動運用）。
  - **Phase B（書込切替、Out-of-scope）**: CRM 側 `products` を正本化、スプレッドシートを読み取り専用ビュー化。**時期未定、別 ADR**。
  - **Phase C（閉鎖、Out-of-scope）**: スプレッドシート閉鎖、過去データを CRM へ完全移行。**時期未定、別 ADR**。
- **新規ファイル**:
  - `migrations/070_add_spreadsheet_phase.sql`（`public.tenant_settings` or `{tenant_xxx}.tenant_settings` に `spreadsheet_phase` 列追加、デフォルト `'A'`）
  - `frontend/src/pages/admin/PhaseSwitchPage.tsx`（Phase 表示のみ、v1.2 では切替 UI 非機能 / 「Phase A 固定」を表示）
  - `backend/app/services/phase_gate.py`（Phase A 時に `inventory_movements` への記録は OK、`products.stock_quantity` 更新は warning + skip）
  - `scripts/export_inventory_for_sheet.py`（Phase A の CSV 出力、運用担当者がスプレッドシートに反映）
- **Acceptance criteria**:
  - **AC9.1**: Phase A 設定下で F6 の承認操作を実行 → `inventory_movements` には記録されるが `products.stock_quantity` は変化せず、warning toast「Phase A: スプレッドシート併走中、在庫数の真値は GS」が表示される。
  - **AC9.2**: `scripts/export_inventory_for_sheet.py --tenant 4 --since YYYY-MM-DD` で承認済 `inventory_movements` を CSV 出力 → 列構成（product_id, delta_qty, occurred_at, supplier_id, operator_id, notes）が運用想定通り。
  - **AC9.3**: Phase 切替は admin のみ可能、`require_permission("phase.switch")`（ただし v1.2 では `'A'` 固定運用、`'B'` / `'C'` への切替は UI 上 disabled）。
  - **AC9.4**: Phase 切替履歴が `audit_log`（既存 or 新規）に記録される（将来 B/C 切替時の証跡用）。
  - **AC9.5**: Playwright で `/admin/phase-switch` を開き、現在 Phase A が表示され、B/C ボタンが disabled で「別 ADR で検討中」のツールチップが出ることを確認。
  - **AC9.6**: Sprint 6 の承認 UI で「Phase A: GS が真値」warning が常時表示される（AC9.1 と整合）。

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

### UF2: マスタ運用（中央 admin、定期メンテ）

1. Jarvis 運用 admin（ひとしさん／しんごさん）が `/super-admin/masters` を開く（F2）
2. Knowledge タブで先週解析に失敗した unparsed token を確認 → `public.knowledge_rules` に rule を新規作成
3. TCG タブで先週発売の新シリーズを `public.tcg_series_master` に追加
4. Suppliers タブで新規仕入元 #46 を `public.suppliers` に追加（`supplier_type` 選択）、Discord routing を `public.supplier_discord_routing` に設定
5. LLM 設定で当月予算超過しそうなら一時的に `public.tenant_llm_budgets.hard_stop = true` で停止

### UF3: Phase A 並走運用フロー（admin、当面長期、v1.2 で範囲縮小）

1. admin が Phase A 状態で Discord 受信＋解析を運用開始（F5 + F3/F4）
2. 中央 admin がレビュー UI で承認（F6）→ `inventory_movements` に記録
3. `products.stock_quantity` は更新されない（Phase A 仕様、warning toast）
4. `scripts/export_inventory_for_sheet.py --tenant 4` で CSV 出力 → 運用担当者がスプレッドシートに反映
5. スプレッドシートの真値 vs CRM の `inventory_movements` 集計 を定期突き合わせ（運用 reconciliation）
6. **Phase B / C 切替の判断は時期未定**、CRM が軌道に乗ったタイミングで別 ADR を起案（spec v1.2 範囲外）

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

### Sprint 9: Phase A 並走運用整備（F9、v1.2 で範囲縮小）

- **Includes**: F9（Phase A のみ、B/C は Out-of-scope）
- **Definition of done**:
  - migration 070 適用、`spreadsheet_phase` 列追加（デフォルト `'A'`）
  - `/admin/phase-switch` で現在 Phase A が表示され、B/C は disabled
  - F6 承認時に `inventory_movements` 記録 + `products.stock_quantity` skip + warning toast 表示（AC9.1）
  - `scripts/export_inventory_for_sheet.py` が `inventory_movements` から CSV 出力（AC9.2）
  - Phase 切替履歴の audit_log 記録経路（B/C 切替時の証跡用）
- **Acceptance criteria covered**: AC9.1〜9.6
- **Verification gates**: Cross-feature smoke 全 8、Fresh tenant onboarding、Sprint 6 の承認 UI で warning 常時表示
- **Out-of-scope (Sprint 9)**: Phase B 書込切替、Phase C スプレッドシート閉鎖、`scripts/import_inventory_from_sheet.py`、Phase B/C UI トグルの実機能化（すべて別 ADR で時期判断）

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

### マルチテナント migration 適用（v1.1 マーケットプレイス型対応）

A6 確定により、本仕様の migration は **`public` schema 配置のもの**（047〜053 の大半）と **`{tenant_xxx}` schema 配置のもの**（054 の RBAC 拡張、F8 用 PO 拡張）の 2 種類に分かれる。Generator は migration ファイル内で `SCHEMA public.` を明示的に書き、`_TENANT_TABLES_SQL` テンプレート（`backend/app/services/tenant.py`）には **テナント別 migration のみ** 反映する。ADR-034 経由の自動適用ループでは:
- `public` migration: 全体で 1 回のみ実行
- `{tenant_xxx}` migration: 全テナント + 新規テナントに対し各 1 回実行

`public.pokemon_dex` / `public.trainer_dex` / `public.tcg_series_master` / `public.suppliers` / `public.products` / `public.knowledge_rules` / `public.supplier_aliases` / `public.discord_inbound_messages` / `public.inventory_movements` / `public.tenant_llm_budgets` は **すべて中央共有**。

### Out-of-scope（v1.1、別 ADR 候補）

1. **同一商品への複数テナント発注重複防止**: 在庫数は仕入元提示数そのまま、コミット差し引きなし（A6 確定）。複数セラーが同じ商品に発注を重ねるリスクは初期実装ではノーガード、運用カバー。将来は「在庫予約 / hold」テーブルで対応する別 ADR を起案。
2. **中央 admin によるレビュー結果の自動反映パス**: A1 確定により全件人手承認のみ。信頼スコア閾値運用（v1.0 案 B）、仕入元別自動運用（v1.0 案 C）は別 ADR。
3. **中央 admin と テナント admin の階層 RBAC 詳細設計**: `is_super_admin` フラグ + `central.*` / `tenant.*` 権限キーは本仕様で導入するが、詳細な権限ツリー（central.knowledge.read だけ付与する中間ロール 等）は別 ADR。
4. **`{tenant_xxx}.tenant_profile`**: F8 で必要だが、既存に無ければ別 migration（055 以降）で導入。テナント側 admin が「印鑑画像 upload」「会社情報編集」できる UI 含めて別 Sprint 候補。
5. **既存 `tenant_004.products` → `public.products` データ移行**: F9 Phase C で実施想定だが、データ整合性確認 / ダウンタイム計画は本仕様の AC では未網羅。本番適用前に Generator がランブックを起案する。
6. **LLM 月次予算の初期値設定**: A2 で「実コスト 1 ヶ月計測後に admin UI 設定」と決定したため、初期値は spec では既定せず、運用で決める。
7. **Postgres declarative partitioning** (`public.inventory_movements`): A3 で「半年後（2026-11）に評価」と決定。本仕様には含まない。
8. **Phase B 書込切替** (v1.2 追加): CRM 側 `products` を正本化、スプレッドシートを読み取り専用ビュー化。時期未定、CRM が軌道に乗ってから別 ADR で判断（memory: `project_jarvis_phase_a_long_term`）。
9. **Phase C スプレッドシート閉鎖** (v1.2 追加): 過去データの CRM 完全移行、`scripts/import_inventory_from_sheet.py` のバルク import。Phase B が安定運用 1-2 ヶ月後の別 ADR で判断。
10. **既存 `tenant_004.products` → `public.products` データ移行** (v1.2 で範囲明確化): Phase C 着手時の前提条件、別 ADR でランブック化（Out-of-scope #5 と統合）。

### Verification（Planner Self-check）

- [x] 全 Sprint に Playwright 検証可能な AC が書かれている
- [x] 既存ファイルパスへの言及がある（新規実装ではなく拡張になっている）
- [x] migration 番号が既存と衝突しない（最新 046 + 1 〜 054 を提案、Notes に注記）
- [x] Discord webhook の HMAC 署名検証パターンが Meta webhook 流用と明記（Notes 節）
- [x] `supplier_aliases` の i18n 対応（language 列）が含まれる（F1, migration 048）
- [x] 段階的廃止の Phase A/B/C 切替手順が運用可能なレベルで書かれている（F9, UF3, AC9.x）
- [x] **v1.1 追加**: A1〜A6 確定値が反映され、Q セクションは「確定事項」セクションに置き換え済み
- [x] **v1.1 追加**: マーケットプレイス型マルチテナント設計（public / tenant schema 分離）が F1 で明示、`tenant_id` 列の配置基準が明確
- [x] **v1.1 追加**: LLM プロバイダが Gemini 2.5 Flash に統一（Claude API への参照削除）
- [x] **v1.1 追加**: 中央 admin / テナント admin の権限二層が F2, F6 で明示
- [x] **v1.1 追加**: PO 出力がテナント名義 + 仕入元 supplier_type による敬称分岐（A4）に対応
- [x] **v1.1 追加**: Out-of-scope 7 項目を明示
- [x] **v1.2 追加**: Phase A 並走長期化方針、F9 / UF3 / Sprint 9 を Phase A 運用整備に絞り込み
- [x] **v1.2 追加**: Phase B（書込切替）/ Phase C（閉鎖）を Out-of-scope #8/#9 に移動
- [x] **v1.2 追加**: Sprint 1-8 develop merged 後（PR #507-522）に Sprint 9 が現実的範囲で着手可能

---

## 確定事項（v1.0 の Q1〜Q6 への回答、2026-05-21 ひとしさん／しんごさん確定）

### A1: 解析結果の承認フロー → **全件人手承認** (v1.0 案 A)

F3 ルール / F4 LLM の `confidence` 値に関わらず、すべての解析結果は F6 レビュー画面で担当者が承認した後でのみ `products` / `inventory_movements` に反映される。

**Definition of Done への組み込み**: F6 のレビューフローで confidence が UI に表示されるが、自動承認パスは v1.1 では実装しない。Sprint 6 以降の運用観察で「閾値運用（案 B）」「仕入元別運用（案 C）」への移行余地は残す（別 ADR）。

### A2: LLM コスト上限超過時の挙動 → **hard_stop=true + admin 通知** (v1.0 案 A) / プロバイダは **Gemini 2.5 Flash**

- 上限超過後は rule_v1 のみで処理、unparsed は次月へ持ち越し（メッセージは `discord_inbound_messages` に保存、`parse_status = budget_exhausted`）
- admin への通知は Discord webhook 経由
- LLM プロバイダは **Google Gemini 2.5 Flash**（既存運用に整合、コスト効率重視）。Claude API は使わない。

**未確定**: 月次予算の初期値（USD）は spec 内では既定せず、初期テナント `tenant_004` / `tenant_006` で実コストを 1 ヶ月計測してから admin UI で設定する運用とする。

### A3: 在庫移動履歴の保持世代 → **全件永久保持** (v1.0 案 A)

`inventory_movements` は append-only で全件永久保持。半年後（2026-11 想定）に行数とクエリ負荷を計測し、必要であればパーティショニング（PostgreSQL declarative partitioning）を別 ADR で導入。

### A4: 仕入元マスタの個人 / 法人混在 → **type 列追加** (v1.0 案 A)

`suppliers.supplier_type ENUM('individual', 'corporate')` を migration 047 で追加（または別 migration 番号、F1 で確定）。PO PDF 生成時に:
- `individual` → 「{name} 様」
- `corporate` → 「{name} 御中」

の敬称を自動で付与（F8 の `po_renderer.py` で分岐）。

### A5: 営業の在庫検索の検索式 → **全 7 種横断 + AND/OR 切替 UI**

`InventorySearchBar` は以下 7 種を **全て横断**:
- ja: `products.name` + `pokemon_dex.name_ja` + `trainer_dex.name_ja`
- en: `products.name_en` + `pokemon_dex.name_en` + `trainer_dex.name_en`
- `products.expansion_code`
- `products.card_number`
- `products.jan_code`
- `supplier_aliases.alias_text`
- `tcg_series_master.name_ja` / `name_en`

UI には **AND/OR トグル**（複数キーワード入力時の挙動切替）を明示的に配置。レスポンス時間制約は **500ms 以内**（F7 AC7.6 で機械検証）。

### A6: マルチテナント時のスコープ → **マーケットプレイス型マルチテナント設計**

v1.0 の選択肢（A 完全分離 / B 共有+上書き / C 分離+import）はいずれも当てはまらない。確定設計は以下:

#### 中央 / `public` schema 配置（全テナント共通、Jarvis 運用 admin のみメンテ）
- `suppliers` 45 社（Jarvis 運用 admin のみ追加・編集・閲覧）
- `products` / `inventory`（**仕入元 Discord 提示数そのまま**、コミット差し引きなし）
- `pokemon_dex` / `trainer_dex` / `tcg_series_master`
- `knowledge_rules` / `supplier_aliases`（admin のみメンテ・閲覧）
- `discord_inbound_messages`
- `tenant_llm_budgets`（テナント別の予算管理だが配置は public、`tenant_id` で識別）
- `inventory_movements`（中央集計、tenant_id 付き）

#### テナント別 / `{tenant_xxx}` schema 配置（既存通り、Phase 1-B-2 で確立）
- `companies` / `contacts` / `deals`
- `quotes` / `quote_items`
- `invoices` / `invoice_items`
- `orders`
- `purchase_orders` / `purchase_order_items`（**各テナント名義で発注**、PO PDF には各テナントの会社名・印鑑・連絡先）
- `users` / `role_permissions`

#### 権限ルール
- 中央マスタ（suppliers / knowledge_rules / supplier_aliases）の編集・閲覧: **Jarvis 運用 admin のみ**（`is_super_admin` flag 等で識別）
- テナント admin: テナント内ユーザーへの「在庫の閲覧範囲」をロールで絞ることが可能（カラム edit 不可）
- 在庫データ自体: **全テナントが閲覧・検索可能**（マーケットプレイス的に他テナントが見える）

#### 発注 (PO) の挙動
- 各テナント名義で仕入元に発注（PO PDF に各テナント会社情報）
- **同一商品に複数テナントから発注重複するリスクは初期実装ではノーガード**（運用カバー、Out-of-scope 参照）
- `quantity` は「仕入元が Discord で提示した数」そのまま表示。中央コミット済み数の差し引きは行わない

---

## Audit notes（Mode A 起案、外部仕様 audit ではない）

本仕様は brief `~/.claude/plans/synchronous-wishing-sun.md` を Mode A（短い idea → 完全仕様）として展開したもの。Mode B（外部仕様 audit）ではないため audit rubric は適用せず。前 spec.md（Sales Anchor / shingo-ops の ADR-021 Sprint 5）は別件のため `spec-prev-adr021-sprint5.md` に退避し、本ファイルでフル書き換え。

**v1.1 更新（2026-05-21）**: v1.0 起案後の Q1〜Q6 回答（ひとしさん／しんごさん）を反映。最大の変更は Q6 から派生した **マーケットプレイス型マルチテナント設計**（在庫・商品マスタ・仕入元・正規化辞書を `public` schema 中央共有、顧客・見積・発注は `{tenant_xxx}` schema 別）。F1 のスキーマ配置、F2 の権限二層、F4 の LLM プロバイダ（Gemini 2.5 Flash）、F6 の承認権限（中央 admin のみ）、F7 の検索式（全 7 種 + AND/OR）、F8 の PO テナント名義出力 + 敬称分岐 を更新。Out-of-scope 7 項目追加。v1.0 起案版は `.claude-pipeline/spec-v1.0.md` に保管。

**v1.2 更新（2026-05-22）**: Sprint 1-8 の develop merge 完了（PR #507-522）を踏まえ、ひとしさん × しんごさん協議で **Phase A 並走を当面長期運用形態として確定**。spec の F9 / UF3 / Sprint 9 を「段階的廃止 Phase A → B → C 切替」から「Phase A 並走運用整備」に絞り込み、Phase B（書込切替）/ Phase C（スプレッドシート閉鎖）は Out-of-scope #8/#9 に移動（時期未定、CRM 軌道に乗ってから別 ADR で判断）。これにより Sprint 9 は現実的な範囲で着手可能。Overview / Goals G5 も同方針に整合。memory: `project_jarvis_phase_a_long_term`。
