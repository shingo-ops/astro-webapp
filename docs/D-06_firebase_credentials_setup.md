# D-6: Firebase認証情報セットアップガイド

## 概要

Jarvis CRMはFirebase Authentication（Google Identity Platform）を認証基盤として使用します。
バックエンドAPIがFirebase IDトークンを検証するため、サービスアカウントキー（firebase-credentials.json）が必要です。

## たとえ話で理解する

Firebase認証は「身分証発行所」のようなものです:
- ユーザーがログインすると、Firebaseが**身分証（IDトークン）**を発行
- バックエンドはその身分証が本物かどうか、Firebaseに問い合わせる
- バックエンドが問い合わせるためには **専用の鍵（サービスアカウントキー）** が必要

このガイドでは、その専用の鍵を取得してVPSに配置する手順を説明します。

## 現在の状況

VPS上には**ダミーファイル**（`{}`のみ）が配置されています。
このため、Firebase認証は実質動作していません（API自体は起動していますが、認証時にエラーになります）。

```bash
# 現状確認
ssh ubuntu@49.212.137.46
cat astro-webapp/firebase-credentials.json
# → {} （ダミー）
```

## セットアップ手順

### Phase 1: GCPコンソールで秘密鍵を発行

1. **GCPコンソールにアクセス**
   - URL: https://console.cloud.google.com/
   - プロジェクト: `sales-ops-with-claude` を選択

2. **IAMと管理 → サービスアカウント**を開く
   - URL直接: https://console.cloud.google.com/iam-admin/serviceaccounts?project=sales-ops-with-claude

3. **既存のサービスアカウントを確認**
   - 通常 `firebase-adminsdk-XXXXX@sales-ops-with-claude.iam.gserviceaccount.com` という名前のアカウントが存在
   - 存在しない場合は「サービスアカウントを作成」で新規作成
     - 名前: `firebase-adminsdk`
     - ロール: `Firebase Admin SDK Administrator Service Agent`

4. **秘密鍵を発行**
   - サービスアカウント名をクリック
   - 「キー」タブ
   - 「鍵を追加」→「新しい鍵を作成」
   - キーのタイプ: **JSON**
   - 「作成」をクリック → 自動的にダウンロード

5. **ダウンロードしたファイルを確認**
   - ファイル名例: `sales-ops-with-claude-XXXXXXXXXX.json`
   - 中身: `{"type": "service_account", "project_id": "sales-ops-with-claude", ...}`

⚠️ **このファイルは絶対にGitHubにコミットしないこと！**

### Phase 2: VPSに配置

#### 方法1: scpで転送（推奨）

```bash
# Mac側で実行
scp ~/Downloads/sales-ops-with-claude-XXXXXXXXXX.json ubuntu@49.212.137.46:/home/ubuntu/astro-webapp/firebase-credentials.json
```

#### 方法2: catでコピペ転送

```bash
# Mac側
cat ~/Downloads/sales-ops-with-claude-XXXXXXXXXX.json
# 表示された内容をコピー

# VPS側
ssh ubuntu@49.212.137.46
cat > /home/ubuntu/astro-webapp/firebase-credentials.json << 'EOF'
（コピーした内容を貼り付け）
EOF
```

### Phase 3: 権限設定

```bash
ssh ubuntu@49.212.137.46
chmod 600 /home/ubuntu/astro-webapp/firebase-credentials.json
ls -la /home/ubuntu/astro-webapp/firebase-credentials.json
# -rw------- 1 ubuntu ubuntu XXXX Apr  XX XX:XX firebase-credentials.json
```

### Phase 4: バックエンドコンテナを再起動

```bash
ssh ubuntu@49.212.137.46
cd astro-webapp
docker compose restart backend celery-worker celery-beat
```

### Phase 5: 動作確認

#### バックエンドログ確認
```bash
docker compose logs backend --tail=20
# Firebase初期化エラーが出ていないこと
```

#### コンテナ内から認証ファイル確認
```bash
docker compose exec backend python -c "
import json
with open('/app/firebase-credentials.json') as f:
    data = json.load(f)
print('Project ID:', data.get('project_id'))
print('Client Email:', data.get('client_email'))
"
```

期待される出力:
```
Project ID: sales-ops-with-claude
Client Email: firebase-adminsdk-XXXXX@sales-ops-with-claude.iam.gserviceaccount.com
```

## D-13: Firebase認証E2Eテスト

D-6完了後に実施します。

### Step 1: Firebaseでテストユーザーを作成

1. https://console.firebase.google.com/project/sales-ops-with-claude/authentication/users
2. 「ユーザーを追加」
3. メール: `test@example.com`
4. パスワード: 強力なパスワード（Bitwardenで生成）
5. **重要**: MFAを有効化（テストアプリでも本番ルールを守る）

### Step 2: クライアント側からログイン

```bash
# IDトークンを取得（Firebase REST API経由）
TOKEN=$(curl -X POST "https://identitytoolkit.googleapis.com/v1/accounts:signInWithPassword?key=YOUR_FIREBASE_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"email":"test@example.com","password":"PASSWORD","returnSecureToken":true}' \
  | jq -r '.idToken')

echo $TOKEN
```

### Step 3: バックエンドAPIを呼び出し

```bash
# トークンを使ってAPIアクセス
curl -H "Authorization: Bearer $TOKEN" https://jarvis-claude.uk/api/v1/customers

# 期待される結果（テナント作成前）: 403 テナントが無効です
# 期待される結果（テナント作成後）: 200 [] (空配列)
```

## D-14: テナント作成・データ操作テスト

D-13完了後、管理者テナント・ユーザーを作成して以下を確認:

```bash
# 1. 管理者でテナント作成
curl -X POST -H "Authorization: Bearer $ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  https://jarvis-claude.uk/api/v1/admin/tenants \
  -d '{"tenant_name":"テスト株式会社","tenant_code":"test-corp"}'

# 2. 顧客作成
curl -X POST -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  https://jarvis-claude.uk/api/v1/customers \
  -d '{"name":"山田太郎","email":"yamada@example.com","company":"山田商事"}'

# 3. 顧客一覧取得
curl -H "Authorization: Bearer $TOKEN" \
  https://jarvis-claude.uk/api/v1/customers

# 4. ダッシュボード確認
curl -H "Authorization: Bearer $TOKEN" \
  https://jarvis-claude.uk/api/v1/dashboard
```

## トラブルシューティング

### バックエンドが起動しない

```bash
docker compose logs backend --tail=30
```

よくあるエラー:
- `JSONDecodeError`: ファイルの中身が正しいJSONでない
- `Permission denied`: chmod 600 でも読めない場合は所有者を確認
- `Project ID mismatch`: GCPプロジェクトが間違っている

### 認証時に「無効な認証トークンです」エラー

- IDトークンの有効期限切れ（1時間で失効）→ 再ログイン
- Firebase Project IDの不一致 → credentials.jsonとフロントエンド設定を確認

### MFA設定エラー

開発中は `.env` で `MFA_REQUIRED=false` にして回避可能ですが、本番運用前に必ず`true`に戻してください。

## セキュリティ注意事項

| 項目 | 対策 |
|------|------|
| firebase-credentials.json の漏洩 | .gitignoreで除外、chmod 600、Bitwardenにバックアップ保管 |
| 鍵の有効期限 | デフォルトで永続。漏洩疑い時は即座にローテーション |
| ローテーション頻度 | 6ヶ月ごと（B-11_credential_management_policy.md準拠） |
| 鍵の漏洩時対応 | 1) GCPで該当鍵を即座に削除 2) 新しい鍵を発行 3) インシデント対応Playbook起動 |

## ローテーション手順（6ヶ月ごと）

```bash
# 1. GCPコンソールで新しい鍵を発行（Phase 1の手順を再実行）

# 2. VPSに配置（既存ファイルを上書き）
scp new-credentials.json ubuntu@49.212.137.46:/home/ubuntu/astro-webapp/firebase-credentials.json

# 3. 権限設定
ssh ubuntu@49.212.137.46 "chmod 600 /home/ubuntu/astro-webapp/firebase-credentials.json"

# 4. バックエンド再起動
ssh ubuntu@49.212.137.46 "cd astro-webapp && docker compose restart backend celery-worker celery-beat"

# 5. 動作確認後、GCPコンソールで古い鍵を削除
```
