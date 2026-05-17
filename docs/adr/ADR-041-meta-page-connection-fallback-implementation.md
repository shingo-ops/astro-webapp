# ADR-041: Meta（Facebook）ページ接続フォールバック実装

## ステータス
Draft

## 背景

ADR-037の調査レポート（docs/research/）で以下が確定：
- Sales Anchorの現状OAuthスコープに `business_management` が含まれない（意図的設計）
- `list_user_pages()` は `/me/accounts` のみ実装、Business Manager管理ページの
  フォールバック未実装
- 多くのB2B顧客はページをBusiness Managerで管理しており、現状実装では
  構造的に接続不能

ガードレール問題はADR-042（別ADR）で対応。

## What

### 1. OAuth スコープ拡張
Facebook OAuthのスコープに `business_management` を**単独で**追加（既存スコープと併存）。
他の権限（pages_manage_engagement, leads_retrieval等）は本ADRには含めない
（Meta審査リスク分散のため、必要時点で別途申請）。
Meta App Review 再申請が前提。

### 2. `list_user_pages()` の Business Manager 対応
以下の経路を順次試行し、結果をマージしてユニーク化：
- `/me/accounts`（既存）
- `/me/businesses` → 各 business に対して `/{business-id}/owned_pages`
- `/{business-id}/client_pages`（クライアント管理ページ）

各経路は独立してエラーハンドリングし、1つが失敗しても他を試行する。

### 3. エラーハンドリング改善
- 空配列時のエラーメッセージを「Pageを作成して」から
  「Facebook連携の権限状態を確認してください」に変更
- 各経路のHTTPエラー（403等）を分離してユーザー向け文言に反映

### 4. 既存テナント向け再認証フロー
- 既存テナント（tenant_006 含む）は古いスコープで接続済み
- UI に「Facebook 連携を更新してください」バナー
- 再OAuth ボタン → 新スコープで再接続
- 旧スコープでも当面動作するように後方互換維持

## Why
- B2B顧客はほぼ全員 Business Manager でページを管理しており、構造的に接続不能
- Meta App Review 審査動画の撮影が、tenant_006 のページ接続失敗で停止中
- ローンチ後のエンタープライズ顧客で必ず再現する問題
- 撮影は本ADR実装完了 + Meta審査承認後に新スコープで撮り直し、
  ローンチ時のフローと完全一致させる方針

## Scope外
- System User Token 方式への移行（別検討、現状ユーザーOAuth維持）
- Meta App Review の手続きそのもの（コード変更外）
- Meta App Review 申請動画の作成（screenplay v3 として別途作成）
- Instagram 側の同様問題（IGは別ADRで対応）
- ガードレール対策（ADR-042で別途）
- business_management 以外の追加スコープ（必要時に個別申請）

## 事業上の制約
- Meta App Review 審査時間：3〜14日
- 撮影シナリオは新スコープでの OAuth フローを反映する必要があり、
  実装完了 + Meta承認後に撮り直し
- 既存テナント（tenant_006含む）の再認証案内が必要
- 申請動画はビジネス用Page・Business Manager管理ページを使用する想定
