# ADR-041: Meta（Facebook）ページ接続フォールバック実装

## ステータス
Proposed（Hikky-dev レビュー指摘反映済み・実装Sprint着手時にAcceptedへ遷移）

## 背景

ADR-037 の調査レポート (`docs/research/ADR-037-meta-page-connection-investigation-report.md`)
で以下が確定：
- Sales Anchor の現状 OAuth スコープは 6 permission（business_management 含まない、意図的設計）
- `list_user_pages()` は `/me/accounts` のみ実装、Business Manager 管理ページのフォールバック未実装
- 多くの B2B 顧客はページを Business Manager で管理しており、構造的に接続不能
- ADR-037 レポートは「business_management 追加は App Review 通過後の Phase 2」を推奨

ガードレール問題は ADR-042（別ADR）で対応。

### Meta App Review の現状と本ADRの判断（Hikky-dev Major#3 への回答）

2026-05-17 時点で、Meta App Review は **未提出** （Shingo 確認済み）。
よって ADR-037 レポートが警告した「審査リセットリスク」は発生しない。
最初から 7 permission（business_management 含む）で申請する判断を下す。
撮影シナリオも新スコープでの OAuth フローを前提として作成する。

### 関連コード referent

- 既存 OAuth スコープ: `backend/app/routers/meta_inbox.py:56` (`_OAUTH_SCOPE`)
- 既存 `list_user_pages()`: `backend/app/services/meta_graph.py:367`
- 既存テナント設定: `migrations/040_create_tenant_meta_config.sql`
- 既存テスト: `backend/tests/test_meta_oauth_scope.py:37-86`
- caller: `backend/app/routers/meta_inbox.py:393`

## What

### 1. OAuth スコープ拡張
Facebook OAuth のスコープに `business_management` を**単独で**追加（既存 6 permission と
併存、合計 7 permission）。他の権限（`pages_manage_engagement`, `leads_retrieval`,
`marketing_messages_messenger` 等）は本 ADR に含めない（Meta 審査リスク分散）。

### 1.1 既存テストの改修（Hikky-dev Major#1 への対応）
本 ADR 実装と**同一 PR 内**で以下のテストを改修：
- `test_meta_oauth_scope.py:37-51`: 6→7 permission に拡張、`business_management` を expected に追加
- `test_meta_oauth_scope.py:64-78`: forbidden list から `business_management` を除外。
  `pages_manage_engagement`, `leads_retrieval`, `marketing_messages_messenger` 等は
  forbidden のまま維持
- `test_meta_oauth_scope.py:81-86`: count を 6→7 に変更、テスト名も更新

### 2. `list_user_pages()` の Business Manager 対応
以下の経路を順次試行：
- `/me/accounts`（既存）
- `/me/businesses` → 各 business に対して `/{business-id}/owned_pages`
- `/{business-id}/client_pages`（クライアント管理ページ）

各経路は独立してエラーハンドリング。

### 2.1 結果の合成契約（Hikky-dev Major#4 への対応）
- **戻り値型**: ユニーク化済 `list[Page]`
- **全経路エラー時のみ** `MetaGraphAPIError` 集約を raise
- **dedupe key**: `page.id`（同一 id は先勝ち）
- **access_token 優先順位**: `/me/accounts` > `owned_pages` > `client_pages`
- **部分失敗**（一部経路エラー、他は成功）: 成功結果のみ返す + 警告ログ
- **rate limit 配慮**: `/me/businesses` が 0 件なら `owned_pages`/`client_pages` はスキップ

### 3. エラーハンドリング改善
- 空配列時のエラーメッセージを「Page を作成して」から
  「Facebook 連携の権限状態を確認してください」に変更
- 各経路の HTTP エラー（403 等）を分離してユーザー向け文言に反映

### 4. 既存テナント向け再認証フロー（Hikky-dev Major#2 への対応）
- `migrations/046_add_granted_scopes.sql` で `tenant_meta_config` に
  `granted_scopes JSONB` 列を追加
- 既存全行に旧 6 permission を backfill（migration 内で実行）
- 再 OAuth 成功時に新スコープを `granted_scopes` に書き込み
- 再認証要否判定: `granted_scopes` に `business_management` が含まれるか否か
- UI に「Facebook 連携を更新してください」バナー表示
- **後方互換維持の終了条件**（Hikky-dev Minor#2 への対応）:
  全テナント新スコープ再接続完了 **OR** ADR 適用後 90 日経過、のいずれか早い方まで。
  それ以降は旧スコープ接続を強制再認証フローに乗せる

## Why
- B2B 顧客はほぼ全員 Business Manager でページを管理しており、現状実装では構造的に接続不能
- Meta App Review が未提出のため、最初から 7 permission で申請可能（審査リセットリスクなし）
- 撮影シナリオが Business Manager ページ前提に確定したため、旧スコープでの提出自体が
  撮影と矛盾する
- ローンチ後のエンタープライズ顧客で必ず再現する問題を、ローンチ前に解決する

## Scope外
- System User Token 方式への移行（別検討、現状ユーザーOAuth維持）
- Meta App Review の手続きそのもの（コード変更外）
- Meta App Review 申請動画の作成（screenplay v3 として別途作成）
- Instagram 側の同様問題（IGは別ADRで対応）
- ガードレール対策（ADR-042で別途）
- `business_management` 以外の追加スコープ（必要時に個別申請）
- **ADR-038 QA Smoke Suite scene-04 への影響評価**（Hikky-dev Minor#1 への対応）:
  本 ADR 実装 Sprint 内で評価、必要に応じて scene-04 を新 OAuth フローに合わせて更新。
  scene-04 改修を同一 PR で扱うか別 follow-up PR で扱うかは実装着手時に判断

## 事業上の制約
- Meta App Review 審査時間：3〜14日
- 既存テナント（tenant_006 含む）の再認証案内が必要
- 申請動画はビジネス用 Page・Business Manager 管理ページを使用する想定
- 後方互換維持期間中、tenant_006 を含む既存テナントは旧スコープのまま動作することを保証

## ステータス遷移（Hikky-dev Nit#2 への対応）
本 ADR は `Proposed` で develop に merge し、実装 Sprint 着手時に `Accepted` に遷移する。
実装完了 + Meta App Review 承認 + 全テナント再認証完了時点で `Implemented` に遷移。
