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
Facebook OAuthのスコープに `business_management` を追加（既存スコープと併存）。
Meta App Review 再申請が前提。

### 2. `list_user_pages()` の Business Manager 対応
以下の経路を順次試行し、結果をマージしてユニーク化：
- `/me/accounts`（既存）
- `/me/businesses` → 各 business に対して `/{business-id}/owned_pages`
- `/{business-id}/client_pages`（クライアント管理ページ）

### 3. エラーハンドリング改善
- 空配列時のエラーメッセージを「Pageを作成して」から
  「Facebook連携の権限状態を確認してください」に変更
- 各経路のHTTPエラー（403等）を分離してユーザー向け文言に反映

### 4. 既存テナント向け再認証フロー
- 既存テナントは古いスコープで接続済み
- UI に「Facebook 連携を更新してください」バナー
- 再OAuth ボタン → 新スコープで再接続

## Why
- B2B顧客はほぼ全員 Business Manager でページを管理しており、構造的に接続不能
- Meta App Review 審査動画の撮影が、tenant_006 のページ接続失敗で停止中
- ローンチ後のエンタープライズ顧客で必ず再現する問題

## Scope外
- System User Token 方式への移行（別検討、現状ユーザーOAuth維持）
- Meta App Review の手続き自体
- Instagram 側の同様問題（IGは別ADRで対応）
- ガードレール対策（ADR-042で別途）

## 事業上の制約
- Meta App Review 審査時間：3〜14日
- 撮影シナリオへの影響：新スコープ反映 vs 応急処置で撮影、の判断が別途必要
- 既存テナント（tenant_006含む）の再認証案内が必要
