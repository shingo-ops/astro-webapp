# Meta 連携・App Review 引き継ぎ資料

**作成日:** 2026-05-18（最終更新: 2026-05-19）  
**作成者:** Terminal Claude Code（shingo-ops セッション）  
**リポジトリ:** `shingo-ops/salesanchor`

---

## 1. この資料の範囲

### 対象（引き継ぐもの）

- Meta（Facebook + Instagram）連携の技術的な問題
- tenant_006（review@salesanchor.jp）の接続障害対応
- Meta App Review 申請（撮影 → 提出）

### 対象外（Shingo + Web Claude で共同開発継続）

- ADR-042 ワークフロー整理（ひとしとの MTG）
- CLAUDE.md・セッション指示の整合化
- Sales Anchor の他機能（注文管理・顧客マスタ・KPI 等）
- deploy.yml・CI 全般の管理
- 撮影の進行（Shingo 主導、パートナーは技術サポート）

---

## 2. Meta 連携の現状（一言で）

| 項目 | 状態 |
|------|------|
| 本番デプロイ | ✅ SUCCESS（2026-05-19 05:37 UTC、Run #26078492490） |
| migration 055（granted_scopes 列）| ✅ 全テナントに自動適用済み（Verify ステップ通過） |
| `/channels` エンドポイント | ✅ HTTP 500 → 復旧のはず（要ブラウザ確認） |
| Facebook Page 接続 | 要確認（OAuth フロー再テスト必要） |
| Meta App Review 撮影 | 🔲 未着手（本復旧確認後に着手可能） |
| Meta App Review 提出 | 🔲 未着手 |

**最初にやること:** `https://app.salesanchor.jp/channels`（review@salesanchor.jp でログイン）を開いて動作確認する。

---

## 3. Meta 連携の技術スタック

### 3-1. 関係するファイル

| ファイル | 役割 |
|---------|------|
| `backend/app/routers/meta_inbox.py` | Meta API エンドポイント（OAuth・Webhook・channels）|
| `backend/app/services/meta_graph.py` | Meta Graph API クライアント |
| `backend/app/tasks/verify_meta_subscriptions.py` | Webhook 定期検証タスク |
| `frontend/src/pages/ChannelsPage.tsx` | 接続管理 UI |
| `migrations/055_add_granted_scopes.sql` | granted_scopes 列追加（テンプレート、全テナント展開）|
| `scripts/migrate_adr041_granted_scopes.py` | migration 055 を全テナントに適用するスクリプト |
| `.github/workflows/deploy.yml` | デプロイ時に migration 055 を自動実行（ADR-045 で追加）|

### 3-2. 重要テーブル: `tenant_XXX.tenant_meta_config`

```sql
-- 各テナントスキーマ内に存在（tenant_001, tenant_006 等）
CREATE TABLE tenant_meta_config (
    id                              SERIAL PRIMARY KEY,
    tenant_id                       INTEGER,
    page_id                         VARCHAR(100),         -- Facebook Page ID
    page_name                       VARCHAR(255),         -- Facebook Page 名
    page_access_token_encrypted     BYTEA,                -- Fernet 暗号化済みトークン
    page_token_expires_at           TIMESTAMPTZ,
    instagram_business_account_id   VARCHAR(100),
    instagram_username              VARCHAR(100),
    subscribed_fields               JSONB,                -- webhook フィールド一覧
    connected_by_staff_id           INTEGER,
    connected_at                    TIMESTAMPTZ,
    is_active                       BOOLEAN,
    granted_scopes                  JSONB                 -- ← ADR-041/migration 055 で追加
);
```

**`granted_scopes` の役割:**  
OAuth で取得したスコープ一覧を JSON 配列で保存。
`business_management` が含まれているかどうかで「再認証が必要か」を判定する。

### 3-3. OAuth フロー

```
ユーザーが /channels で「接続」クリック
    ↓
GET /api/v1/meta/oauth/start
    ↓（Meta 側で承認）
POST /api/v1/meta/oauth/callback（code を受け取る）
    ↓
meta_graph.py: GET /me?fields=id,name,accounts
                GET /me/accounts（管理 Page 一覧）
    ↓
tenant_meta_config に page_access_token + granted_scopes を保存
    ↓
webhook 購読設定（subscribed_fields）
```

**ADR-041 で変更した箇所（`meta_inbox.py:284` 付近）:**
- INSERT 時に `granted_scopes` カラムを含めるよう変更
- `GET /channels` で `granted_scopes` の fallback を追加

### 3-4. 環境設定

| 変数名 | 内容 |
|--------|------|
| `META_APP_ID` | 1250869697105619 |
| `META_APP_SECRET` | GitHub Secret に保存（VPS .env に自動書き込み） |
| `META_VERIFY_TOKEN` | Webhook 検証トークン |
| `META_OAUTH_REDIRECT_URI` | https://api.salesanchor.jp/api/v1/meta/oauth/callback |
| `METADATA_FERNET_KEY` | アクセストークン暗号化キー（GitHub Secrets + 別の安全な場所にバックアップ必須） |

> ⚠️ **METADATA_FERNET_KEY を紛失すると全テナントのトークンが永久に復号不能になる。**  
> ローテーション手順: `docs/operations/meta_encryption_key_rotation.md`

---

## 4. Meta 領域のタイムライン（2026-05-14〜現在）

### 5/14 — CI を静かに壊したコミット（後で判明）

```
dac01e3  feat: auto-apply HUMAN_AGENT tag, remove messaging window UI
```

このコミットが pytest / Schema Check / E2E を複合的に壊した。
当時は Meta とは無関係のリリースに紛れて気づかれなかった。

### 5/17 — Facebook Page 接続問題の発覚

tenant_006（review@salesanchor.jp）で Meta App Review の撮影準備中に、
Facebook Page が接続できないことを発見。

```
症状: GET /me/accounts → 空配列 [] が返る
調査: Facebook 設定ページの Business Integration が削除されていた
```

| PR | 内容 |
|----|------|
| #383 / #385 | ADR-037 起案 + レポート（Meta ページ接続経路の調査） |
| #384 / #386 | ADR-040 起案 + レポート（Claude Code ガードレール調査） |

### 5/17〜18 — ADR-041 起案・レビュー・改訂

```
93b81e6  初版起案（ひとし指摘で Major 不備 4 点発見）
1cf7fde  改訂版（Major #1〜#4 対応）
f0e1905  PR #388 develop マージ（起案確定）
```

**ひとし（Hikky-dev）レビューで発覚した主な問題:**
- Business Integration 削除の意図・経緯が不明
- `/me/accounts` 空返却時の fallback フロー不明確
- `granted_scopes` の定義と使用箇所が乖離

### 5/18 — ADR-041 自動実装（PR #389）

```
74dfb6a  Claude Max ADR implementation (20260517-154629) (#389)
```

**PR #389 で追加された主なもの:**
- `meta_inbox.py` の connect_callback に `granted_scopes` 保存ロジック
- `meta_inbox.py` の list_channels に `granted_scopes` fallback
- `migrations/055_add_granted_scopes.sql`（テンプレート）
- `scripts/migrate_adr041_granted_scopes.py`（全テナント展開スクリプト）

> ⚠️ **ここに後の本番障害の種があった:**  
> migration 055 のスクリプトは追加されたが、`deploy.yml` への自動実行ステップ追記が漏れた。

### 5/18 朝 — CI 健全性回復（ADR-044）

5/14 のコミット以来壊れていた CI を修復。

| PR | 修正内容 |
|----|---------|
| #391 | ADR-044 起案 |
| #392 | Schema Check 修復（PYTHONPATH 追加、migration 014 欠落解消、E2E sidebar hover 修正、i18n ADR-021 準拠） |
| #393 | 追加修復（`exec_driver_sql` バインドパラメータ誤解釈、PYTHONPATH 追加） |

### 5/18 朝 — develop → main リリース（PR #390）

```
5c5e4e7  Merge pull request #390 from shingo-ops/develop
```

CI 全 SUCCESS を確認してマージ。直後に `deploy.yml` が自動発火。

### 5/18 06:00 UTC — 本番デプロイ失敗 #1

```
Run ID: 26016317982  conclusion: failure
fatal: Need to specify how to reconcile divergent branches.
```

VPS の `git pull origin main` が divergent branches エラーで終了。

**修正（PR #394）:**
```diff
- git pull origin main
+ git fetch origin main
+ git reset --hard origin/main
```

### 5/18 06:10 UTC — 本番デプロイ成功 → 障害発覚

```
Run ID: 26016671960  conclusion: success
```

デプロイ自体は成功したが、`/channels` が HTTP 500 に。
→ 後述「§5 本番障害の詳細」参照。

### 5/18 午後 — ADR-045 で障害対応

| PR | 内容 |
|----|------|
| #395 | ADR-045 起案（migration 055 deploy 自動化） |
| #396 | 実装：deploy.yml に migration 055 自動実行 + Verify ステップ追加 |
| #398 | Release: ADR-045 → main マージ |

### 5/19 05:37 UTC — 本番復旧

```
Run ID: 26078492490  conclusion: success
```

`migrate_adr041_granted_scopes.py` が全テナントに migration 055 を適用。  
Verify ステップ（全テナント走査、`RAISE EXCEPTION` で不整合を検出）が通過。

---

## 5. 本番障害の詳細

### 5-1. 症状

- URL: `https://app.salesanchor.jp/channels`（tenant_006）
- HTTP ステータス: 500 Internal Server Error
- UI: "An internal error occurred. Please contact support."
- 影響: 既存 Facebook Page の表示不可 / 新規接続不可

### 5-2. エラーログ（VPS より）

**一次エラー（connect_callback: `meta_inbox.py:284`）:**
```
UndefinedColumnError: column "granted_scopes" of relation "tenant_meta_config" does not exist
[SQL: INSERT INTO tenant_meta_config (..., granted_scopes) VALUES (..., CAST($10 AS jsonb)) RETURNING id]
```

**連鎖エラー（list_channels: `meta_inbox.py:794`）:**
```
InFailedSQLTransactionError: current transaction is aborted, commands ignored until end of transaction block
→ GET /api/v1/meta/channels HTTP/1.1" 500 Internal Server Error
```

### 5-3. 根本原因

```
PR #389（ADR-041 実装）
  ├── migrations/055_add_granted_scopes.sql 追加 ✅
  ├── scripts/migrate_adr041_granted_scopes.py 追加 ✅
  ├── meta_inbox.py が granted_scopes 列を参照するよう変更 ✅
  └── deploy.yml に migration 実行ステップを追記 ❌ ← 漏れ

↓ main リリース（PR #390）

コード:  granted_scopes を INSERT / SELECT する最新版
DB:      granted_scopes 列が存在しない旧版

↓

UndefinedColumnError → HTTP 500
```

### 5-4. 修正内容（PR #396 / ADR-045）

`deploy.yml` に 2 つのブロックを追加:

**① migration 実行（deploy ステップ内）:**
```bash
# ADR-041 / ADR-045: 全テナントの tenant_meta_config に granted_scopes 追加 + backfill
docker exec -w /app astro-webapp-backend-1 \
  python scripts/migrate_adr041_granted_scopes.py
```

**② Verify ステップ（deploy 後の確認）:**
```sql
DO $$
DECLARE r RECORD; missing_col_count INT := 0; null_rows_total INT := 0; cnt INT;
BEGIN
    FOR r IN SELECT id, tenant_code, ... FROM public.tenants WHERE is_active = true LOOP
        -- tenant_meta_config.granted_scopes 列の存在チェック
        -- NULL レコードが残っていないかチェック
        -- 異常があれば RAISE EXCEPTION でデプロイを止める
    END LOOP;
    RAISE NOTICE 'ADR-045 verification OK';
END $$;
```

**冪等性:** `ADD COLUMN IF NOT EXISTS` + `UPDATE WHERE granted_scopes IS NULL` で再実行安全。

---

## 6. 関連 ADR / PR（Meta 領域）

| ADR | ファイル | PR | 内容 |
|-----|---------|-----|------|
| ADR-024 | ADR-024_meta_integration_structural_fix.md | — | Meta 統合の構造的修正（旧版） |
| ADR-025 | ADR-025_meta_integration_operational_hardening.md | — | Meta 統合の運用強化（3点セット要件） |
| ADR-034 | ADR-034-tenant-migration-automation.md | — | テナント migration 自動化 |
| ADR-037 | ADR-037-meta-page-connection-investigation.md | #383 / #385 | Meta ページ接続経路の現状調査 |
| ADR-041 | ADR-041-meta-page-connection-fallback-implementation.md | #388 / #389 | Meta ページ接続フォールバック実装 ← **本体** |
| ADR-044 | ADR-044-ci-health-recovery.md | #391 / #392 / #393 | develop CI 健全性回復（ADR-041 関連修復）|
| ADR-045 | ADR-045-migration-055-deploy-automation.md | #395 / #396 / #398 | migration 055 deploy 自動化（本番障害対応）|

---

## 7. 残課題（Meta 範囲に絞る）

### 7-1. 最優先（今すぐ）

- [ ] ブラウザで `https://app.salesanchor.jp/channels`（review@salesanchor.jp）を開いて HTTP 200 を確認
- [ ] 既存 Facebook Page（Shingo Tanizawa）が表示されることを確認
- [ ] 「再接続」で OAuth フローが通ることを確認（7 permission 付与）

### 7-2. 高（数日以内）

**screenplay v3 の作成:**
- 既存: `docs/meta-app-review/META_APP_REVIEW_SCREENCAST_SCRIPT.md`（v2）
- 変更点:
  - 7 permission OAuth フロー対応（`business_management` が追加された）
  - Business Manager 管理 Page の選択画面
  - 既存テナント向け「再認証バナー」は映さない（review 専用テナントでは不要）
  - scene1〜7 の全フロー確認

**撮影実施:**
- `scripts/recording/salesanchor_recording.py` 参照
- tenant_006 のデモデータ確認（`scripts/qa/seed-tenant.sql`）

**Meta App Review 提出:**
- permissions 申請: `pages_messaging`, `instagram_manage_messages`, `business_management`
- Use case demo video を各 permission ごとに用意

### 7-3. 中（撮影一段落後）

- scene3/4/7 の E2E カバレッジ回復（PR #392 で縮退した部分）
- granted_scopes 再認証バナーの本番テナント向けテスト（HIGH LIFE JPN）

---

## 8. 引き継ぎ後の行動計画

### Day 1（引き継ぎ当日）

- [ ] この資料 + ADR-041 + ADR-044 + ADR-045 を通読
- [ ] `https://app.salesanchor.jp/channels` で動作確認（review@salesanchor.jp）
- [ ] Shingo と引き継ぎ MTG（30 分、Meta 領域のみ）

### Week 1

- [ ] screenplay v3 作成 → Shingo に確認
- [ ] 撮影実施（Shingo 主導、技術サポート）
- [ ] Meta App Review 提出（Meta 側の審査: 3〜14 日）

### Week 2 以降

- [ ] Meta 審査対応（追加質問・修正依頼）
- [ ] scene3/4/7 E2E カバレッジ回復
- [ ] granted_scopes 再認証フローの本番テスト

---

## 9. 共同開発との境界

以下は **このドキュメントの対象外**。Shingo + Web Claude で共同開発を継続:

| 項目 | 担当 |
|------|------|
| ADR-042 ワークフロー整理（ひとし提案） | Shingo + Web Claude + ひとし |
| CLAUDE.md・セッション指示の整合化 | Shingo + Web Claude |
| Sales Anchor の他機能（注文・顧客・KPI 等） | Shingo + Web Claude |
| deploy.yml・CI 全般の管理 | Shingo + Web Claude |
| ADR 起案・実装パイプライン | 引き続き claude-pipeline で自動化 |

---

## 10. 主要参照リンク

| 用途 | リンク / パス |
|------|--------------|
| リポジトリ | github.com/shingo-ops/salesanchor |
| 本番 App | https://app.salesanchor.jp/ |
| 本番 API | https://api.salesanchor.jp/ |
| 旧ドメイン（並行稼働中） | https://jarvis-claude.uk/ |
| VPS | ubuntu@49.212.137.46（SSH: Shingo 権限）|
| ADR-041 | docs/adr/ADR-041-meta-page-connection-fallback-implementation.md |
| ADR-044 | docs/adr/ADR-044-ci-health-recovery.md |
| ADR-045 | docs/adr/ADR-045-migration-055-deploy-automation.md |
| 撮影台本 v2 | docs/meta-app-review/META_APP_REVIEW_SCREENCAST_SCRIPT.md |
| 撮影スクリプト | scripts/recording/salesanchor_recording.py |
| QA シード SQL | scripts/qa/seed-tenant.sql |
| Fernet キー操作 | docs/operations/meta_encryption_key_rotation.md |
| CLAUDE.md | /CLAUDE.md（開発ルール共通） |

---

*このドキュメントは Terminal Claude Code が 2026-05-18〜19 のセッション中に作成しました。  
事実はコミット SHA・PR 番号・VPS ログから引用しています。*
