# B-10: アクセス権限棚卸し手順書

## 目的
SSH鍵・DBユーザー・GitHub権限を月次で確認し、不要な権限を削除する。

## 最終更新: 2026-04-06

---

## 実施タイミング
毎月第1月曜日

---

## チェックリスト

### 1. SSH鍵の確認

```bash
ssh ubuntu@49.212.137.46

# 登録済みの公開鍵一覧
cat ~/.ssh/authorized_keys

# 各鍵のコ��ント（メールアドレス等）を確認し、
# 現在のプロジェクトメンバーと照合す��
```

**確認事項:**
- [ ] 退職・契約終了したメンバーの鍵が残っていないか
- [ ] 不明な鍵がないか
- [ ] rootユーザーのauthorized_keysが空であること

### 2. DBユーザーの確認

```bash
docker compose exec postgres psql -U myapp_user -d myapp_db -c \
  "SELECT usename, usesuper, usecreatedb, valuntil
   FROM pg_user ORDER BY usename;"
```

**確認事項:**
- [ ] 不要なDBユーザーがいないか
- [ ] スーパーユーザー権限が必要最小限か
- [ ] アプリ接続用ユーザー（myapp_user）がスーパーユーザーでないこと

### 3. GitHub リポジトリ権限

```bash
# Collaborator一覧（GitHub CLI使用）
gh api repos/shingo-ops/astro-webapp/collaborators --jq '.[].login'
```

**確認事項:**
- [ ] 不要なCollaboratorがいないか
- [ ] Write権限を持つメンバーが必要最小限か
- [ ] Deploy Keyが必要なものだけか

### 4. Firebase / GCP権限

1. https://console.firebase.google.com → プロジェクト設定 → アクセス管理
2. 不要なメンバーがいないか確認

**確認事項:**
- [ ] 不要なIAM��ーザー・サービスアカウントがないか
- [ ] APIキーが必要最小限か

### 5. Cloudflare権限（導入後）

1. https://dash.cloudflare.com → メンバー管理
2. 不要なメンバーがいないか確認

---

## 結果記録

| 実施日 | SSH鍵 | DBユーザー | GitHub | Firebase | 対応事項 | 実施者 |
|--------|-------|-----------|--------|----------|---------|--------|
| YYYY/MM/DD | OK/要対応 | OK/要対応 | OK/要対応 | OK/要対応 | 内容 | 名前 |
