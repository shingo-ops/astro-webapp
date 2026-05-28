# Secret ローテーション手順

GitHub Actions で使用している Secret の更新手順です。
`monthly-secret-expiry.yml` が 180 日以上未更新の Secret を検出したときに参照してください。

## 対象 Secret 一覧

| Secret 名 | 用途 | 保管場所 |
|-----------|------|---------|
| `PIPELINE_PAT` | CI/CD 用 GitHub Personal Access Token | しんごさんの GitHub アカウント |
| `SSH_PRIVATE_KEY` | VPS デプロイ用 SSH 秘密鍵 | ローカル `~/.ssh/` |
| `META_APP_SECRET` | Meta (Facebook) API シークレット | Meta for Developers ダッシュボード |
| `DISCORD_WEBHOOK_OWNER_PING` | Discord owner-ping 通知 URL | Discord サーバー設定 |
| `DISCORD_WEBHOOK_SCHEDULED_REPORT` | Discord 定期レポート通知 URL | Discord サーバー設定 |
| `DISCORD_WEBHOOK_PR` | Discord PR 通知 URL | Discord サーバー設定 |
| `METADATA_FERNET_KEY` | Meta トークン暗号化キー | 本番環境 `.env` |

## 手順

### 1. GitHub Secrets の更新ページを開く

```
https://github.com/shingo-ops/salesanchor/settings/secrets/actions
```

### 2. 対象 Secret を選択して「Update」

- 該当する Secret 名の行にある **Update** ボタンをクリック
- 新しい値を貼り付けて保存

### 3. 各 Secret の新しい値の取得方法

#### `PIPELINE_PAT`
1. GitHub → Settings → Developer settings → Personal access tokens → Tokens (classic)
2. 既存トークンを削除 → **Generate new token (classic)**
3. スコープ: `repo` + `workflow` にチェック
4. 生成されたトークンをコピーして GitHub Secrets に貼り付け

#### `SSH_PRIVATE_KEY`
1. `ssh-keygen -t ed25519 -C "salesanchor-deploy"` で新しいキーを生成
2. 公開鍵を VPS の `~/.ssh/authorized_keys` に追加
3. 秘密鍵（`cat ~/.ssh/id_ed25519`）を GitHub Secrets に貼り付け

#### `META_APP_SECRET`
1. [Meta for Developers](https://developers.facebook.com/apps/) → アプリを選択
2. Settings → Basic → App Secret の「Show」をクリック
3. 値をコピーして GitHub Secrets に貼り付け

#### `DISCORD_WEBHOOK_*`
1. Discord サーバー → チャンネル設定 → 連携サービス → ウェブフック
2. 既存 Webhook の URL をコピー（または新規作成）
3. GitHub Secrets に貼り付け

#### `METADATA_FERNET_KEY`
1. 本番 VPS にログイン
2. `docker compose exec backend python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"` で新しいキーを生成
3. `.env` の `METADATA_FERNET_KEY` を更新 → `docker compose restart backend`
4. 同じ値を GitHub Secrets に貼り付け

### 4. 動作確認

```bash
# GitHub Actions で workflow_dispatch 実行
gh workflow run monthly-secret-expiry.yml --ref main
```

実行結果が「✅ 全 Secret が 180 日以内に更新済み」になれば完了です。
