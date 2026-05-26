# システム品質監査レポート
**実施日**: 2026-05-06  
**対象リポジトリ**: shingo-ops/salesanchor  
**調査者**: Shingo Terminal Claude Code

---

## 1. CI（自動テスト）

### ワークフロー一覧（`.github/workflows/`）

| ファイル | 発火条件 | 概要 |
|---|---|---|
| `test.yml` | PR/push（`backend/`, `migrations/`, `.github/workflows/test.yml` 変更時）→ `main`, `develop` | pytest（SQLite + PostgreSQL RLS）、Redis サービス、Fernet 鍵生成 |
| `deploy.yml` | `main` push のみ | LP build (Astro 4) → rsync → git pull → docker compose → migration → health check |
| `discord-pr-notify.yml` | PR opened/reopened/closed、review submitted | PR 通知を Discord `DISCORD_WEBHOOK_PR` に送信 |
| `claude-pipeline.yml` | `develop` push で `docs/adr/ADR-*.md` 追加時、または手動 | ADR を Claude Code で実装 → PR 作成 → Discord 通知 |
| `e2e.yml` | PR/push（`frontend/`, `.github/workflows/e2e.yml` 変更時）→ `main`, `develop` | Playwright E2E（chromium）、API mock、Firebase Auth mock |
| `_archive/` 2本 | 廃止済み | phase1-b2 マイグレーション用（使用停止） |

### テストファイル

- **フロントエンド（ユニット/統合）**: **ない**（`*.test.ts`, `*.spec.tsx` 等なし）
- **フロントエンド（E2E）**: **あり** — `frontend/tests-e2e/` 配下に 8 本
  - `scene1-dashboard.spec.ts` 〜 `scene8-data-deletion.spec.ts`
- **バックエンド**: **あり** — `backend/tests/` 配下に 32 本（`test_*.py`）
  - `conftest.py`, `db.py` 含む

### テストカバレッジ

- **あり**（`pytest-cov==6.1.1` インストール済）
- 設定: `backend/pytest.ini`（`testpaths = tests`）

### Lint / Format チェック

- **ない** — ruff, black, flake8, eslint, prettier 等の設定なし
- Playwright E2E で TypeScript type check（`tsc --noEmit`）のみ実行

---

## 2. ステージング環境

- **Staging ブランチ**: **ない**（`develop` / `main` の2ブランチ構成）
- **ステージング向けデプロイワークフロー**: **ない**
- **補足**: `develop` はインテグレーションブランチで自動デプロイなし。`main` push のみ本番へ自動デプロイされる。

---

## 3. ブランチ保護

- **ドキュメント**: `docs/BRANCH_PROTECTION_SETUP.md`
- **対象**: `main` ブランチ（GitHub Rulesets）
- **設定内容**:
  - Force push 禁止: ✅
  - Deletion 禁止: ✅
  - Required reviews: 0（少人数チームのため PR 通過のみ）
  - Required status checks: **設定なし**（CI pending でもマージ可能）
  - Bypass: admin（shingo-ops）のみ、緊急時 §4 に記録必須
- **develop ブランチ保護**: **ない**（Ruleset 未設定）
- **PR 時に CI 緑必須**: **ない**（status checks 未設定のため）

---

## 4. 本番デプロイ

- **ワークフロー**: `.github/workflows/deploy.yml`
- **発火条件**: `main` ブランチへの push のみ（手動・タグなし）
- **デプロイフロー**:
  1. LP build (Astro 4)
  2. SSH → rsync で LP dist/ を VPS へ転送
  3. `git pull origin main`
  4. Meta Webhook 環境変数を `.env` に追記（既存値は上書きしない）
  5. `docker compose up -d --build`（全コンテナ再構築）
  6. 20 秒待機
  7. Migration 39 本を順序通り psql 実行（CREATE IF NOT EXISTS / idempotent）
  8. `curl /api/health` で health check
  9. `docker image prune`
- **デプロイ前 backup**: **ない**（migration は idempotent 設計で代替）
- **Discord 通知（デプロイ完了）**: **部分的にあり** — 失敗時のみログ出力（Webhook 通知なし）

---

## 5. ロールバック

- **手順書**: **あり**（3本）
  - `docs/PHASE1_DEPLOYMENT.md` — git checkout → docker compose up でロールバック
  - `docs/B-04_incident_response_playbook.md` — 初動1時間・調査24時間・復旧フロー
  - `docs/PHASE5_DOMAIN_CUTOVER_RUNBOOK.md` — ドメイン切替の parallel listen → ロールバック手順
- **緊急 revert + 再デプロイ ワークフロー**: **ない**（手動対応）
- **DB マイグレーションのロールバック**: **部分的にあり** — 全 SQL が idempotent（破壊的変更なし）。`TRUNCATE/DROP TABLE` は運用判断で手動実施。Alembic downgrade 機能は未導入。

---

## 6. 本番監視

- **/health エンドポイント**: **あり**
  - `backend/app/routers/health.py`
  - DB 接続確認（`SELECT 1`）、`/api/health` で公開
  - deploy.yml 内で自動 health check 実行
- **UptimeRobot / Pingdom / Sentry**: **ない**（設定・参照なし）
- **Prometheus / Grafana / Loki**: **あり（設定済み）**
  - `monitoring/` 配下
  - `monitoring/prometheus/alert_rules.yml` — 7 本のアラートルール
    - HighCpuUsage（>80%, 5分）、HighMemoryUsage（>85%）、HighDiskUsage（>80%）
    - HighDbConnections（>80）、PostgresDown、HighErrorRate（5xx >10/5m）、ServiceDown
  - Grafana provisioning: `monitoring/grafana/provisioning/`（alerting, datasources, dashboards）
  - Loki rules: `monitoring/loki/rules/jarvis/alerts.yml`
- **エラーログ Discord 通知**: **ない**（Prometheus alert からの Discord 通知は未設定）

---

## 7. データベース運用

- **マイグレーション方式**: **あり（カスタム SQL）**
  - `migrations/` 配下に 001〜039 の SQL ファイル（39 本）
  - 全て `CREATE TABLE IF NOT EXISTS` / `ADD COLUMN IF NOT EXISTS` / `CREATE INDEX IF NOT EXISTS` — idempotent 設計
  - Alembic は未使用（カスタムスクリプト採用）
  - 新テナント作成: `backend/app/services/tenant.py` のテンプレート（015〜017, 019〜022）で自動生成
- **バックアップ**: **あり**
  - `scripts/backup.sh` — 日次 pg_dump → gzip（VPS ローカル）
  - `scripts/backup_to_s3.sh` — S3 remote backup（3-2-1 ルール、90日 retention、cron 毎日 3:30）
- **復元テスト記録**: **あり** — `docs/B-09_restore_test_procedure.md`

---

## 8. シークレット管理

### GitHub Actions Secrets 一覧（値不要）

| Secret 名 | 用途 |
|---|---|
| `DISCORD_WEBHOOK_PR` | PR 通知 |
| `DISCORD_WEBHOOK_PLAN_REVIEW` | ADR 実装通知 |
| `SSH_PRIVATE_KEY` | VPS SSH 接続 |
| `VPS_HOST` | VPS IP/ドメイン |
| `VPS_USER` | VPS ユーザー名 |
| `META_VERIFY_TOKEN` | Webhook 検証トークン |
| `META_APP_SECRET` | Meta App secret |
| `META_APP_ID` | Meta App ID |
| `META_OAUTH_REDIRECT_URI` | OAuth callback URI |
| `METADATA_FERNET_KEY` | Page Access Token 暗号化鍵 |

- **`.env.example`**: **あり** — `.env.example`（全キー名 + プレースホルダ値）
- **VPS `.env` バックアップ**: **あり** — GitHub Secrets に保管（`docs/ENVIRONMENT_VARIABLES.md`）
- **APIキーローテーション手順**: **あり** — `docs/B-11_credential_management_policy.md`

---

## 9. ドキュメント

- **README.md**: **あり**（最終更新 2026-04-30, commit `93c05a5`）
  - 内容: 概要、Tech Stack、Domains、Branch Strategy、Phase 進捗、Key Documents、Local Development、Tests、Deployment、License
- **docs/ 配下のドキュメント一覧**（44 ファイル/ディレクトリ）:

| ファイル | 概要 |
|---|---|
| `ACCESS_CONTROL.md` | アクセス制御設計 |
| `ADR-009_discord_gateway.md` | Discord Gateway ADR（Phase 3） |
| `adr/` | ADR ディレクトリ（ADR-011.md 現存） |
| `B-04_incident_response_playbook.md` | インシデント対応プレイブック |
| `B-06_cloudflare_setup.md` | Cloudflare 設定 |
| `B-09_restore_test_procedure.md` | リストアテスト手順 |
| `B-10_access_review_procedure.md` | アクセスレビュー手順 |
| `B-11_credential_management_policy.md` | 認証情報管理ポリシー |
| `B-12_offboarding_procedure.md` | オフボーディング手順 |
| `BRANCH_PROTECTION_SETUP.md` | ブランチ保護設定（§3） |
| `DATA_CLASSIFICATION.md` | データ分類 |
| `data_deletion_callback_design.md` | Data Deletion Callback 設計 |
| `decisions/` | 決定記録ディレクトリ（ADR-010 等） |
| `DEVELOPMENT_GUIDE_FOR_SHINGO.md` | Shingo 向け開発ガイド |
| `ENVIRONMENT_VARIABLES.md` | 環境変数リファレンス |
| `FEATURE_SPECIFICATION.md` | 機能仕様書 |
| `FIREBASE_API_KEY_RESTRICTION_GUIDE.md` | Firebase API キー制限ガイド |
| `INCIDENT_RESPONSE.md` | インシデント対応手順 |
| `INTERNAL_TEST_GUIDE.md` | 内部テストガイド |
| `META_APP_REVIEW_*.md` | Meta App Review 撮影チェックリスト・台本 |
| `PHASE_1D_*.md` | Phase 1-D Meta Inbox 設計・リリースノート |
| `PHASE_1E_FOLLOW_UP_BACKLOG.md` | Phase 1-E フォローアップ backlog（25 項目） |
| `PHASE1_DEPLOYMENT.md` | Phase 1 デプロイ・ロールバック手順 |
| `PHASE5_DOMAIN_CUTOVER_RUNBOOK.md` | Phase 5 ドメイン切替 Runbook |
| `products_design.md` | 商品マスタ設計（TCG 11列） |
| `SECURITY.md` | セキュリティ方針 |
| `SECURITY_ENHANCEMENT_ROADMAP.md` | セキュリティ強化ロードマップ |
| `ZERO_TRUST_POLICY.md` | Zero Trust ポリシー |
| `USE_CASE_DESCRIPTIONS_v1.1_DRAFT.md` | Meta App Review 申請文書 |
| `D-06_firebase_credentials_setup.md` | Firebase 認証情報セットアップ |
| ~~`D-17_password_manager_setup_guide.md`~~ | 削除済（未使用ツールのガイドのため） |
| `フェーズ1_セキュリティ基盤_実装ガイド.docx` | セキュリティ実装ガイド（Word） |
| `B-2_discord_setup_guide_for_shingo.docx` | Discord セットアップガイド（Word） |

- **アーキテクチャ図**: **ない**（Mermaid、draw.io 等の図ファイルは確認されず。docs/ は文書中心）

---

## チェックリスト総括

| カテゴリ | 項目 | 状態 |
|---|---|---|
| CI | フロントエンド ユニットテスト | **ない** |
| CI | フロントエンド E2E（Playwright） | **あり**（`frontend/tests-e2e/` 8本） |
| CI | バックエンド テスト（pytest） | **あり**（`backend/tests/` 32本） |
| CI | PR 時テスト自動実行 | **あり**（test.yml, e2e.yml） |
| CI | テストカバレッジ計測 | **あり**（pytest-cov） |
| CI | lint/format チェック | **ない** |
| ステージング | staging ブランチ | **ない** |
| ステージング | ステージングデプロイ | **ない** |
| ブランチ保護 | main 保護（Ruleset） | **あり** |
| ブランチ保護 | Required reviews | **ない**（0件） |
| ブランチ保護 | Required status checks | **ない** |
| ブランチ保護 | develop 保護 | **ない** |
| デプロイ | deploy.yml（main push） | **あり** |
| デプロイ | デプロイ前 backup | **ない** |
| デプロイ | Discord 通知（完了） | **部分的にあり**（失敗時ログのみ） |
| ロールバック | 手順書 | **あり**（3本） |
| ロールバック | 緊急 revert ワークフロー | **ない** |
| ロールバック | DB migration ロールバック | **部分的にあり**（idempotent、手動 DROP） |
| 監視 | /health エンドポイント | **あり** |
| 監視 | Sentry / UptimeRobot | **ない** |
| 監視 | Prometheus / Grafana | **あり**（設定済、VPS 連携要確認） |
| 監視 | Discord エラー通知 | **ない** |
| DB | Migration（idempotent SQL） | **あり**（39本） |
| DB | バックアップ（S3 3-2-1） | **あり** |
| DB | 復元テスト手順書 | **あり** |
| シークレット | GitHub Secrets | **あり**（10件） |
| シークレット | .env.example | **あり** |
| シークレット | GitHub Secrets 保管 | **あり** |
| シークレット | ローテーション手順 | **あり** |
| ドキュメント | README.md | **あり**（2026-04-30） |
| ドキュメント | docs/ 運用文書 | **あり**（44ファイル） |
| ドキュメント | アーキテクチャ図 | **ない** |

---

## 全体所感

バックエンドテスト（pytest 32本）・E2E テスト（Playwright 8本）・バックアップ（S3 3-2-1）・Prometheus 監視・運用手順書（インシデント対応含む3本）など、スタートアップとして**必要な要素は広く揃っている**。
ただし lint/format・Required status checks・staging 環境・deploy 成功時の Discord 通知・フロントエンドユニットテストは**未導入**で、CI の網が粗い部分がある。
最優先で対処すべきは「**test.yml が緑でないと main マージできない**ようにする status check の有効化」と「**デプロイ成功/失敗の Discord 通知**の実装」の2点。
