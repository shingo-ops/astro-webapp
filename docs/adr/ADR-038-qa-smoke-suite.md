# ADR-038: QA Smoke Suite — Cross-feature UI verification against real backend

| 項目 | 内容 |
|------|------|
| ステータス | Accepted |
| 作成日 | 2026-05-15 |
| 起案 | ひとし（森本） |
| 関連 ADR | ADR-026（IG message_id TEXT 化）/ ADR-027（i18n）/ ADR-034（テナント migration 自動化、merged 2026-05-14）/ ADR-036（テナントスキーマ整合性、PR #372 で実装中） |

## What

ACS（acceptance criteria）と無関係に **毎スプリント実行される、実 VPS backend 向けの UI smoke suite** を導入する。

### L1: QA Gate tenant + Seed data

`tenant_006` (tenant_review) を **QA Gate tenant + 撮影兼用** として正式位置付け。冪等な seed SQL で「実データ入りの known state」を毎スプリント開始時に reset する。

seed 内容:

| Entity | 件数 | 内訳 |
|--------|------|------|
| users | 3 | admin / staff / viewer 各 1 名、locale ja |
| companies | 5 | うち 2 件 Meta Channel 接続済 |
| contacts | 5 | 各 company に紐づく |
| leads | 5 | status: new / contacted / qualified / lost / won 各 1 |
| orders | 3 | status: draft / confirmed / shipped 各 1 |
| products | 5 | カテゴリ違い |
| meta_messages | 10 | messenger 6 + instagram 4、message_id 100 字超え含む |
| meta_oauth_tokens | 2 | 接続済 2 件用、暗号化 dummy token |
| public.meta_page_routing | 2 | tenant_006 ↔ page_id ↔ ig_account_id |
| settings | 1 | tenant default |

接頭辞ルール (`qa-` / `QA-`) で cleanup が安全に「smoke 残骸」を削除可能。

### L2: Reset script

`scripts/qa/reset-tenant.sh` で `flock` 排他 → tenant_code assert → TRUNCATE → seed 投入 → 行数 assert を実行。実装は冪等。撮影との時間衝突は `flock /tmp/qa-tenant-006.lock` + Discord 通知で排他する。

### L3: 8 smoke scenarios (実 VPS backend 向け)

`tests/qa-smoke/scene-{01..08}.spec.ts` を新規作成。**実 VPS backend (`https://api.salesanchor.jp`) を直接叩く**（既存 `frontend/tests-e2e/scene1-dashboard.spec.ts` 〜 `scene8-data-deletion.spec.ts` は `/api/v1/*` を mock 化していたので、実バグを検出できない）。

既存 mock e2e は **Meta App Review 撮影シナリオ** に特化した命名（scene1-dashboard / scene2-connect-fb-page / scene3-receive-messenger / scene4-reply-messenger / scene5-connect-instagram / scene6-instagram-dm / scene7-human-agent-tag / scene8-data-deletion）で、本 ADR の **領域横断機能 smoke** とは内容が完全に異なる。両者は重複ではなく **目的別の別資産** として並存:
- 既存 `frontend/tests-e2e/` = Meta 撮影シナリオ用 mock e2e（撮影資産 + 高速 CI 用、削除しない・リネームしない）
- 新規 `tests/qa-smoke/` = 領域横断機能 smoke（実 VPS backend、毎スプリント mandatory）

| # | Scenario | 目的 | 所要 |
|---|----------|------|------|
| 01 | Auth & Roles | admin / staff / viewer login、権限切替 | 10m |
| 02 | Dashboard | KPI 表示、console error 0 | 5m |
| 03 | Customers (Companies + Contacts) | 一覧 → 詳細 → 編集 → 新規 → 検索 | 15m |
| 04 | Inbox & Channels | メッセージ受信 → 返信 → DB row 確認、接続済 2 件表示 | 20m |
| 05 | Leads & Orders | 案件 → 受注 lifecycle、売上計算 | 20m |
| 06 | Staff & Permissions | ロール変更 → 権限切替反映 | 10m |
| 07 | i18n & Settings | ja↔en 切替 + 主要 5 画面で `t()` カバレッジ + ハードコード grep | 10m |
| 08 | Data Lifecycle | 顧客 → Channel → mock webhook → 案件 → 受注 → KPI 更新（典型 user journey 通し） | 15m |

合計 1〜2 時間で完走。Playwright fully automated。`tests/qa-smoke/playwright.config.ts` で実 VPS backend 向け設定。

## Why

2026-05-14〜15 に tenant_006 で 3 件のバグが発覚（meta_page_routing 未登録 / meta_messages 9 カラム欠落 / message_id VARCHAR(100)）。これらは **ADR-034 / ADR-036 で構造的に再発防止される** が、もう 1 つ別の問題が並行して存在する:

**Sprint Evaluator は ACS で指定された機能だけ検証する設計** で、ACS 範囲外の領域（隣接機能、UI 全般）は素通りする。AC が「メッセージング機能の改善」だった場合、Customers / Channels / Orders は触らない。

加えて、既存 `frontend/tests-e2e/scene1-dashboard.spec.ts` 〜 `scene8-data-deletion.spec.ts` は Meta App Review 撮影シナリオに特化した mock e2e で、`/api/v1/*` を mock 化しており **実 backend を叩いていなかった**。これでは「PO が 5 分触っただけで見つかる初歩バグ」を検出できない。

本 ADR は **「ACS と無関係に毎スプリント走る、実 backend 向けの UI smoke suite」** を導入し、Evaluator の練度に頼らず機械的にこの種のバグを止める仕組みを作る。ADR-034 (migration 自動化) / ADR-036 (schema 整合性) と組み合わせて、ローンチ前に必要な品質保証 floor を完成させる。

## Scope (IN)

- backend repo `shingo-ops/salesanchor` に以下 10 ファイル追加:
  - `scripts/qa/seed-tenant.sql`
  - `scripts/qa/reset-tenant.sh`
  - `scripts/qa/cleanup-smoke-data.sh`（接頭辞 `qa-` / `QA-` データの削除）
  - `tests/qa-smoke/scene-{01..08}.spec.ts`（8 ファイル）
  - `tests/qa-smoke/playwright.config.ts`
  - `tests/qa-smoke/fixtures/qa-tenant-creds.ts`
  - `tests/qa-smoke/utils/real-backend.ts`
  - `tests/qa-smoke/utils/db-assert.ts`
  - `.github/workflows/qa-smoke.yml`（pull_request + weekly cron + workflow_dispatch、self-hosted runner で実行）
  - `docs/runbooks/qa-smoke-operations.md`
既存ファイルへの変更はなし（既存 mock e2e はリネームせず、Meta 撮影シナリオ資産として保持）。

## Scope (OUT — 明示除外)

- **Fresh tenant onboarding の構造的検証** → **ADR-036（PR #372）に委譲**。ADR-036 の `scripts/setup_tenant.py` 完全版 + `test_tenant_schema_integrity.py` で担保される。本 ADR ではこれを参照するのみで重複実装しない
- **deploy.yml の全テナント migration ループ** → ADR-034（merged）で完了済み
- **病的負荷下の coupling 検証** (1000+ req/s) → VPS 2GB 制約で再現不能、別途 staging canary / k6 Cloud / chaos engineering を要するため、ローンチ後規模拡大時に再検討
- **既存 mock e2e の削除** → 撮影資産 + 高速 CI 用に残す
- **CI lint/typecheck の bootstrap** → 別 ADR で扱う

## Business constraints

- **VPS 2GB**（2026-05-15 確認時 idle 1.3GB 消費、swap 735MB 使用）→ smoke の concurrent N ≤ 10、duration ≤ 30s 上限
- **撮影との衝突回避**: `flock /tmp/qa-tenant-006.lock` + Discord 通知（撮影は 2026-05-15 時点で完了済、以降は通常運用）
- **本 ADR の実装スプリント中は他機能凍結**（seed / scripts / 8 scenario の整備は集中作業、ひとし／しんごさん間で承諾済）
- マージ判断は しんごさん（自動マージ禁止、ADR-012 ルール準拠）

## 成功基準

1. 次回 Evaluator 起動時、`evaluator.md` に `## Cross-feature smoke suite results` 表（全 8 シナリオ green）が必ず含まれる
2. 過去 2026-05-15 の 3 件のバグ（meta_page_routing 未登録 / meta_messages 9 カラム欠落 / message_id VARCHAR(100)）を意図的に再現したとき、scene-04（Inbox & Channels）が確実に FAIL することを Phase 1 終了時に検証
3. ADR-036 の `test_tenant_schema_integrity.py` が pytest CI で必ず走るようになった後、ADR-038 smoke suite と組み合わせて「ACS 外の領域も毎スプリント検証される」状態が完成

## 関連メモリ・ドキュメント

- 本セッション設計プラン: ひとし side local の `~/.claude/plans/generic-skipping-fox.md`
- Evaluator/Generator agent 定義: `~/.claude/agents/{evaluator,generator}.md` Step 3.4 + 0.9/0.10 を本セッションで更新済
- プロジェクト共通真実: `astro-webapp/CLAUDE.md` §QA smoke suite + Fresh tenant onboarding
- 過去 PR: #363（ADR-034 merged）/ #372（ADR-036 merged 2026-05-15 06:39 UTC、commit `56ac477`）/ 2026-05-15 朝の手動修正
- 既存 setup スクリプト: `scripts/setup_tenant.py` / `scripts/setup_review_tenant.py`（ADR-036 で完全版に置き換え済）
- 既存 mock e2e: `frontend/tests-e2e/scene1-dashboard.spec.ts` 〜 `scene8-data-deletion.spec.ts`（Meta App Review 撮影シナリオ）
- ADR-036 follow-up Issue: #375（schema-check.yml が後発 migration の catch-up 漏れを検出できない件）

## Amendment: 実行ポリシー変更（2026-05-27）

### 変更内容
毎ADR実装PRでqa-smoke全件実行（80〜90分）→ PRのdiffに応じた選択実行（10〜20分）

### 理由
- 実態調査により、qa-smokeを実行するself-hosted runner（salesanchor-vps）が未登録で全件実行が機能していないことが判明
- 毎PR全件実行は過剰設計と判断

### 新ポリシー
- 毎ADR実装PR: EvaluatorがPR diffを読み関係シーンのみ実行
- 週次（月曜03:00 JST）: 全8シーン（qa-smoke.yml既存設定）
- develop→main PR: qa-smoke実行なし

### シーン選択ルール
evaluator.md「qa-smoke 実行ポリシー」セクション参照
