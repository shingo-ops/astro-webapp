# ADR-018: Instagram Send API Endpoint 修正

| 項目 | 内容 |
|------|------|
| ステータス | Accepted |
| 作成日 | 2026-05-14 |
| 関連 | ADR-016, 撮影台本シーン 6, Meta App Review |

## コンテキスト

Meta App Review 提出向けスクリーンキャスト撮影直前、撮影台本シーン 6（Instagram 返信送信）が `error code=3 OAuthException "Application does not have the capability to make this API call."` で失敗する事象が判明した。

調査の結果、原因は Sales Anchor の Instagram Send API 実装が誤った endpoint を使用していることが特定された。

Meta 公式ドキュメント "Overview - Instagram Platform" より：
> If your app uses Facebook Login for Business, your app will use the Messenger Platform's Instagram Messaging API to send and receive messages.

Sales Anchor は Facebook Login for Business を採用しているが、Instagram 送信実装は Instagram API with Instagram Login 用の endpoint (`POST /{ig_business_account_id}/messages`) を呼んでいた。正しい endpoint は Messenger Platform の `POST /{page_id}/messages`。

### 診断で確認した事実

| テスト | 結果 |
|--------|------|
| `POST /{ig_business_account_id}/messages` + IGSID | 400 OAuthException code=3 |
| `POST /{page_id}/messages` + IGSID | **200 OK**（message_id 返却） |
| トークンスコープ（debug_token） | `instagram_manage_messages` ✅ 含まれている |
| Messenger 送信（`POST /{page_id}/messages` + PSID） | 200 OK（既存・変更なし） |

## What

Instagram Send API の呼び出し先 endpoint を以下に変更する：

- **変更前**: `POST /{ig_business_account_id}/messages`
- **変更後**: `POST /{page_id}/messages`（Messenger 送信と同一 endpoint）
- `recipient.id` は IGSID のまま維持
- Page Access Token は現行のまま使用
- `send_instagram_message` 関数の引数 `ig_user_id` を `page_id` に変更

## Why

Meta の Messenger Platform では、`POST /{page_id}/messages` endpoint が `recipient.id` の形式で自動判別する：
- PSID → Messenger にディスパッチ
- IGSID → Instagram DM にディスパッチ

`/{ig_business_account_id}/messages` は Instagram API with Instagram Login（新 API、`instagram_business_manage_messages` 使用）向けの endpoint であり、Facebook Login for Business（`instagram_manage_messages` 使用）とは別系統。

## Scope 外

- Messenger 送信実装の変更（既に動作している）
- 受信フローの変更
- OAuth フローの変更
- データベーススキーマの変更
- Webhook 設定の変更

## 変更ファイル

| ファイル | 変更内容 |
|----------|----------|
| `backend/app/services/meta_graph.py` | `send_instagram_message`: `ig_user_id` → `page_id`、URL パス修正 |
| `backend/app/routers/leads.py` | 呼び出し引数: `ig_user_id=str(ig_business_id)` → `page_id=str(page_id_for_send)` |
| `backend/tests/test_message_send.py` | `captured["ig_user_id"]` → `captured["page_id"]` アサーション更新 |

## 受け入れ基準

1. Sales Anchor の Inbox から Instagram 返信を送信して、相手側 Instagram に届く
2. Messenger 返信は引き続き動作している（regression なし）
3. Instagram 受信は引き続き動作している（regression なし）
4. backend ログに Send API 成功レスポンスが記録されている

## 参照

- Meta 公式: [Overview - Instagram Platform](https://developers.facebook.com/docs/instagram-platform/overview/)
- Meta 公式: [Send Messages - Messenger Platform](https://developers.facebook.com/docs/messenger-platform/instagram/features/send-message)
