# ADR インデックス

> このファイルは `scripts/generate-adr-index.js` により自動生成されます。
> **手動編集禁止。** ADR ファイルを追加・変更後に `node scripts/generate-adr-index.js` を実行してください。

最終更新: 2026-05-30 / ADR 総数: 72 件

## 一覧

| 番号 | タイトル | ステータス | 日付 |
|------|---------|-----------|------|
| [ADR-011](./ADR-011.md) | ADR-011: ADR駆動ワークフロー採用 (3者協調モデル) | Proposed | — |
| [ADR-012](./ADR-012-what-how-separation.md) | ADR-012: 開発フロー再設計 — What/How 役割分担モデル採用 | Proposed | — |
| [ADR-013](./ADR-013.md) | ADR-013: ヘッダーロゴと favicon を Sales Anchor 正式ブランドに統一 | Proposed | — |
| [ADR-014](./ADR-014-inventory-management.md) | ADR-014: 在庫管理モジュール — Discord 自動収集 + AI 解析 + 自己改善ループ | Proposed | — |
| [ADR-015](./ADR-015.md) | ADR-015: リード管理モジュール設計 | Proposed | — |
| [ADR-016](./ADR-016.md) | ADR-016: Facebook ドメイン認証メタタグの追加 | Proposed | — |
| [ADR-017](./ADR-017.md) | ADR-017: robots.txt に facebookexternalhit を許可 | Proposed | — |
| [ADR-018](./ADR-018_instagram_send_endpoint_fix.md) | ADR-018: Instagram Send API Endpoint 修正 | Accepted | — |
| [ADR-018](./ADR-018.md) | ADR-018: salesanchor.jp DNS TXTレコードによるMetaドメイン認証 | Proposed | — |
| [ADR-019](./ADR-019-screencast-test-data-creation.md) | ADR-019: Meta App Review 撮影用テストデータの作成方針 | Proposed | — |
| [ADR-019](./ADR-019.md) | ADR-019: Meta審査期間中の英語UI一時デプロイ | ## What | — |
| [ADR-020](./ADR-020.md) | ADR-020: recording/english-ui 本番デプロイ実行 | Superseded | — |
| [ADR-021](./ADR-021-order-management.md) | ADR-021: 受注管理モジュール — フルフィルメント・売上計算・報酬計算の Sales Anchor 統合 | ## コンテキスト | — |
| [ADR-022](./ADR-022.md) | ADR-022: UIをMeta Business Suite風に刷新（左サイドメニュー + 配色統一） | Proposed | — |
| [ADR-023](./ADR-023_staff_lifecycle_three_layer_sync.md) | ADR-023: スタッフライフサイクル操作における認証3層の同期化 | Proposed | — |
| [ADR-024](./ADR-024_meta_integration_structural_fix.md) | ADR-024: Meta 連携の構造的不整合の修正 | — | — |
| [ADR-025](./ADR-025_meta_integration_operational_hardening.md) | ADR-025: Meta 連携の運用整備強化 - 環境変数注入の確実性とパートナー実装ガイドラインの強化 | — | — |
| [ADR-026](./ADR-026_meta_messages_message_id_text.md) | ADR-026: meta_messages.message_id の TEXT 化（Instagram mid 受信対応） | — | — |
| [ADR-027](./ADR-027-ui-internationalization.md) | ADR-027: Sales Anchor UI の i18n 対応（日本語/英語切り替え） | Accepted | — |
| [ADR-028](./ADR-028-screencast-tenant-isolation.md) | ADR-028: Meta App Review 撮影用テナント分離 | Superseded | — |
| [ADR-029](./ADR-029-self-hosted-runner-fleet.md) | ADR-029: Self-hosted runner fleet — 2 台 Mac 体制と labels 戦略の正式化 | Accepted | — |
| [ADR-032](./ADR-032.md) | ADR-032: Firebase Authentication カスタム認証ドメイン | Accepted | — |
| [ADR-033](./ADR-033-app-theme-switching.md) | ADR-033: アプリ内テーマ切り替え（ライト / ダーク） | Accepted | — |
| [ADR-034](./ADR-034-tenant-migration-automation.md) | ADR-034: 新規テナント migration 自動化 + 既存テナント整合化 | Proposed | — |
| [ADR-035](./ADR-035-external-state-verification.md) | ADR-035: External State Verification — 6 system × 5-layer defense | Proposed | — |
| [ADR-036](./ADR-036-tenant-schema-integrity.md) | ADR-036: テナントスキーマ整合性保証 | — | — |
| [ADR-037](./ADR-037-meta-page-connection-investigation.md) | ADR-037: Meta（Facebook/Instagram）ページ接続経路の現状調査 | Draft - 調査フェーズ | — |
| [ADR-038](./ADR-038-qa-smoke-suite.md) | ADR-038: QA Smoke Suite — Cross-feature UI verification against real backend | Accepted | — |
| [ADR-039](./ADR-039-generator-codebase-reconnaissance.md) | ADR-039: Generator Codebase Reconnaissance — ADR 概念と frontend/backend 実体の機械的突き合わせ | Proposed | — |
| [ADR-040](./ADR-040-claude-code-guardrail-investigation.md) | ADR-040: Claude Code 運用ガードレールの存在性調査 | Draft - 調査フェーズ | — |
| [ADR-041](./ADR-041-meta-page-connection-fallback-implementation.md) | ADR-041: Meta（Facebook）ページ接続フォールバック実装 | ## 背景 | — |
| [ADR-042](./ADR-042-guardrails-and-release-flow.md) | ADR-042: Claude Code 運用ガードレール強化 + リリース運用統一 | Accepted | — |
| [ADR-044](./ADR-044-ci-health-recovery.md) | ADR-044: develop ブランチ CI 健全性の回復 | Accepted | — |
| [ADR-045](./ADR-045-migration-055-deploy-automation.md) | ADR-045: ADR-041 migration 055 の本番適用と deploy.yml 自動化 | Accepted | — |
| [ADR-046](./ADR-046-lp-redesign.md) | ADR-046: Landing Page Redesign — English-only, Professional SaaS Style | — | 2026-05-19 |
| [ADR-047](./ADR-047-lp-copy-refocus.md) | ADR-047: LP Copy Refocus — Customer-First Voice + Visual Polish | — | 2026-05-20 |
| [ADR-048](./ADR-048-web-claude-external-planner.md) | ADR-048: Web Claude (claude.ai) as External Auxiliary Planner — Two-Document Reconciliation | — | 2026-05-20 |
| [ADR-049](./ADR-049-lp-section-completion.md) | ADR-049: LP Section Completion Hot-fix — S3 Carousel Cards + S4 Ecosystem Diagram + S5 Metrics Band + S6 Why-us 4-column | — | 2026-05-20 |
| [ADR-050](./ADR-050-release-pr-workflow-standardization.md) | ADR-050: Release PR Workflow Standardization — Pattern A Codification + Branch Protection | — | 2026-05-20 |
| [ADR-051](./ADR-051-claude-pipeline-full-automation.md) | ADR-051: claude-pipeline Full Automation — Reviewer / Evaluator Auto-Trigger | — | 2026-05-20 |
| [ADR-053](./ADR-053-claude-pipeline-decision-parsing-fix.md) | ADR-053: claude-pipeline Reviewer Decision Parsing Fix + Self-Approve Workaround | — | 2026-05-20 |
| [ADR-054](./ADR-054-lp-hubspot-style-restructure.md) | ADR-054: LP Full Restructure — HubSpot-Style Layout + frontend Brand Color Unification | — | 2026-05-20 |
| [ADR-055](./ADR-055-playwright-mcp-setup.md) | ADR-055: Playwright MCP Setup for claude-pipeline Evaluator | — | 2026-05-20 |
| [ADR-056](./ADR-056-human-in-the-loop-minimization.md) | ADR-056: Human-in-the-Loop Minimization — Auto-Regenerate + Auto-Merge to develop + Notification Consolidation | — | 2026-05-20 |
| [ADR-057](./ADR-057-lp-premium-restyle.md) | ADR-057: LP Premium Restyle — HubSpot Construct + Dark Navy Hero + Hub Card Grid | — | 2026-05-20 |
| [ADR-058](./ADR-058-remove-contacts-from-sidebar.md) | ADR-058: サイドバーから「担当者」メニューを削除し会社ページに統合 | Proposed | — |
| [ADR-059](./ADR-059-lead-nav-unified-tabs.md) | ADR-059: リードナビゲーションをアコーディオン→クリック＋ページ内タブに統一 | Accepted | — |
| [ADR-060](./ADR-060-rename-company-to-client-profile.md) | ADR-060: 「会社」→「顧客情報」/ "Companies" → "Client Profile" リネーム | Proposed | — |
| [ADR-061](./ADR-061-inbox-meta-style-layout.md) | ADR-061: Inbox Meta Business Suite スタイル UI 再設計 | Proposed | — |
| [ADR-063](./ADR-063-inbox-page-level-tab-header.md) | ADR-063: Inbox ページレベル ヘッダー + 全幅タブバー | Proposed | — |
| [ADR-064](./ADR-064-inbox-meta-exact-replica.md) | ADR-064: Inbox Meta Business Suite 完全再現レイアウト | Accepted | — |
| [ADR-065](./ADR-065-asyncpg-prepared-statement-cache-disable.md) | ADR-065: asyncpg プリペアドステートメントキャッシュ無効化 | Accepted | — |
| [ADR-066](./ADR-066-dark-mode-logo-invert.md) | ADR-066: ダークモード時サイドバーロゴ白反転 | Accepted | — |
| [ADR-067](./ADR-067-design-token-enforcement.md) | ADR-067: デザイントークン強制システム（Design Token Enforcement） | Accepted | 2026-05-21 |
| [ADR-068](./ADR-068-platform-brand-asset-policy.md) | ADR-068: プラットフォームブランドアセットポリシー | Accepted | — |
| [ADR-069](./ADR-069-uptime-kuma-activation.md) | ADR-069: Uptime Kuma 監視ダッシュボードの有効化 | — | — |
| [ADR-070](./ADR-070-grafana-monitoring-integration.md) | ADR-070: Grafana ドメイン移行 + Uptime Kuma→Prometheus 統合 | — | — |
| [ADR-071](./ADR-071-orders-nav-placement.md) | ADR-071: 受注管理ナビゲーション導線の追加 | — | — |
| [ADR-072](./ADR-072-tenant-schema-prefix-enforcement.md) | ADR-072: tenant schema 修飾の戦略統一（schema prefix と reset_tenant_context のハイブリッド） | Proposed | — |
| [ADR-073](./ADR-073-design-system-kgi-rubric.md) | ADR-073: デザインシステム KGI 100% ルーブリック | — | — |
| [ADR-074](./ADR-074-worktree-agent-enforcement.md) | ADR-074: Worktree強制によるエージェントPR混入防止 | — | — |
| [ADR-075](./ADR-075-github-secrets-only-policy.md) | ADR-075: GitHub Secrets 一元管理ポリシー | — | — |
| [ADR-076](./ADR-076-claude-md-hierarchy.md) | ADR-076: CLAUDE.md 階層構造標準化 + サイズ上限改定 | — | — |
| [ADR-076](./ADR-076-pipeline-efficiency-improvements.md) | ADR-076: パイプライン効率化（Evaluator自動スキップ・Governance自動化・重複検出改善・Researcher自動起動） | — | — |
| [ADR-077](./ADR-077-github-actions-metrics.md) | ADR-077: GitHub Actions CI メトリクスの Prometheus/Grafana 可視化 | — | — |
| [ADR-078](./ADR-078-vps-runner-registration.md) | ADR-078: VPS runner 登録計画 — さくらVPS への salesanchor-vps ラベル付き self-hosted runner 登録 | Accepted | — |
| [ADR-079](./ADR-079-claude-code-monitoring-access.md) | ADR-079: Claude Code 専用 VPS 読み取り専用監視アクセス | Accepted | — |
| [ADR-080](./ADR-080-monitoring-vps-separation.md) | ADR-080: 監視スタックの管理室VPS分離 — RAM危機の根本解決とCIランナー統合 | Proposed | — |
| [ADR-081](./ADR-081-monitoring-vps-final-operational-design.md) | ADR-081: 監視VPS分離の最終運用設計 — パケットフィルタ、UFW、proxy 経路、backend worker 数の固定 | Accepted | — |
| [ADR-081](./ADR-081-remove-design-review-gate.md) | ADR-081: design-review-gate 廃止 — develop までの自動化方針との整合 | Accepted | — |
| [ADR-082](./ADR-082-deploy-skip-migrations-on-frontend-only.md) | ADR-082: フロントのみのデプロイで DB マイグレーション実行をスキップする | Accepted | — |
| [ADR-083](./ADR-083-tcg-type-master.md) | ADR-083: TCG シリーズの「種別」をマスタ表 + UI 管理へ移行する | Accepted | — |
| [ADR-999](./ADR-999-pipeline-test.md) | ADR-999: パイプライン動作テスト | テスト用（マージ後に削除予定） | — |

## ステータス凡例

| ステータス | 意味 |
|-----------|------|
| Accepted | 承認済み・有効 |
| Proposed | 提案中 / レビュー待ち |
| Deprecated | 非推奨（後継 ADR 参照） |
| Superseded | 別 ADR により上書き済み |
