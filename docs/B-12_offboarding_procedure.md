# B-12: 退職・契約終了時のアクセス権剥奪手順

## 目的
退職・契約終了時に全アクセス権を即日削除し、不正アクセスを防止する。

## 最終更新: 2026-04-06

---

## 実施タイミング
**契約終了日当日に実施する。**翌日に持ち越さない。

---

## チェックリスト

### 1. SSH鍵の削除（即日・最優先）

```bash
ssh ubuntu@49.212.137.46

# 対象者の公開鍵を削除
nano ~/.ssh/authorized_keys
# → 対象者の行を削除して保存

# 確認
cat ~/.ssh/authorized_keys
# → 対象者の鍵がないこと
```

### 2. DBユーザーの削除

```bash
# 対象者専用のDBユーザーがある場合
docker compose exec postgres psql -U myapp_user -d myapp_db -c \
  "REVOKE ALL PRIVILEGES ON ALL TABLES IN SCHEMA public FROM <��ーザー名>;
   DROP USER IF EXISTS <ユーザー名>;"
```

### 3. GitHubリポジトリからの削除

```bash
# Collaboratorから削除
gh api -X DELETE repos/shingo-ops/salesanchor/collaborators/<GitHubユーザー名>

# 確認
gh api repos/shingo-ops/salesanchor/collaborators --jq '.[].login'
```

### 4. Firebase / GCPプロジェクトからの削除

1. https://console.firebase.google.com → プロジェクト設定
2. 「ユーザーと権限」から対象者を削除
3. https://console.cloud.google.com → IAM から対象���を削除

### 5. Cloudflareからの削除（導入後）

1. https://dash.cloudflare.com → メンバー管理
2. 対象者を削除

### 6. Bitwardenからの削除

1. Bitwarden組織の管理画面を開く
2. 対象者を組織から削除
3. 共有フォルダへのアクセスが即座に無効化されることを確認

### 7. 共有パスワードの変更

対象者がアクセスしていた認証情報をすべて変更する:

- [ ] VPS管理パスワード
- [ ] PostgreSQLパス��ード（.env更新 + docker compose再起動）
- [ ] Grafana管理者パスワード
- [ ] その他、対象者が知っていた認証情報

```bash
# .env更新後のサービス再起動
docker compose down && docker compose up -d
```

### 8. CRMユーザーアカウントの無効化

```bash
docker compose exec postgres psql -U myapp_user -d myapp_db -c \
  "UPDATE public.users SET is_active = false
   WHERE email = '<対象者メール>';"
```

---

## 完了確認

| # | 項目 | 完了 | 確認者 | 日時 |
|---|------|------|--------|------|
| 1 | SSH鍵削除 | [ ] | | |
| 2 | DBユーザー削除 | [ ] | | |
| 3 | GitHub削除 | [ ] | | |
| 4 | Firebase/GCP削除 | [ ] | | |
| 5 | Cloudflare削除 | [ ] | | |
| 6 | Bitwarden削除 | [ ] | | |
| 7 | 共有パスワード変更 | [ ] | | |
| 8 | CRMアカウント無効化 | [ ] | | |

**全項目にチェックが入るまで、退職処理は完了としない。**
