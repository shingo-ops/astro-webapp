# GitHub Actions Workflows

## discord-pr-notify.yml

PR ライフサイクルイベントを Discord に通知する。

### 通知対象イベント

| イベント | 通知タイトル | 色 |
|---------|------------|----|
| PR作成 (opened) | 🔵 新しいPRが作成されました | 青 |
| PR再オープン (reopened) | 🔄 PRが再オープンされました | 黄 |
| レビュー承認 (approved) | ✅ レビューが投稿されました (承認) | 緑 |
| レビュー修正要求 (changes_requested) | ⚠️ レビューが投稿されました (修正要求) | 赤 |
| レビューコメント (commented) | 💬 レビューが投稿されました (コメント) | 黄 |
| マージ (merged) | 🎉 PRがマージされました | 緑 |
| クローズ (closed, 未マージ) | ❌ PRがクローズされました（未マージ） | 赤 |

### 必要な Secrets

`DISCORD_WEBHOOK_PR` をリポジトリの Secrets に登録する必要があります。

#### 登録手順

1. Discord でチャンネルの Webhook URL を発行
   - チャンネル設定 → 連携サービス → ウェブフック → 新しいウェブフック

2. GitHub リポジトリに Secret を登録
   - Settings → Secrets and variables → Actions
   - New repository secret
   - Name: `DISCORD_WEBHOOK_PR`
   - Value: Discord から取得した Webhook URL

### 動作確認

Secret 登録後、次回以降の PR 作成・レビュー・マージで自動的に Discord に通知されます。

---

## deploy.yml

`main` ブランチへの push 時に VPS（jarvis-claude.uk）へ自動デプロイする。

### トリガー

- `main` ブランチへの push

### デプロイ手順（自動）

1. VPS に SSH 接続
2. `git pull origin main`
3. Meta Webhook 環境変数を `.env` に追記
4. `docker compose up -d --build`
5. ヘルスチェック（`/api/health`）
6. 外部からの疎通確認

### 必要な Secrets

| Secret 名 | 説明 |
|-----------|------|
| `VPS_HOST` | VPS のホスト名または IP |
| `VPS_USER` | SSH ユーザー名 |
| `SSH_PRIVATE_KEY` | SSH 秘密鍵 |
| `META_VERIFY_TOKEN` | Meta Webhook 検証トークン |
| `META_APP_SECRET` | Meta App シークレット |
