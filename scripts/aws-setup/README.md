# AWS S3バックアップ セットアップガイド（D-10）

## 概要

PostgreSQLの日次バックアップをAWS S3に転送する仕組みのセットアップ手順です。
本番運用開始時にこの手順を実施してください。

## たとえ話で理解する

大事な書類を「家の金庫だけ」に保管すると、火事で家ごと燃えたら全て失います。
「家の金庫」+「銀行の貸金庫」の両方に保管しておけば、どちらかが無事です。

- **家の金庫** = VPSローカルのバックアップ（既存）
- **銀行の貸金庫** = AWS S3のバックアップ（このセットアップで追加）

これは「3-2-1ルール」と呼ばれるバックアップの基本原則です:
- **3** つのコピーを持つ
- **2** つの異なるメディアに
- **1** つはオフサイト（離れた場所）に

## コスト見積もり

| 項目 | 月額 |
|------|------|
| S3ストレージ（STANDARD_IA、約9GB） | 約18円 |
| データ転送（アップロードのみ） | 無料 |
| **月額合計** | **約20円** |

## ファイル一覧

| ファイル | 用途 |
|---------|------|
| `iam-policy.json` | バックアップ用IAMユーザーの権限定義（最小権限の原則） |
| `s3-bucket-policy.json` | S3バケットへのHTTPS強制アクセスポリシー |
| `s3-lifecycle.json` | 90日後の自動削除ルール |
| `setup-s3-backup.sh` | S3バケット作成・設定の自動化スクリプト |

---

## セットアップ手順（運用開始時）

### Phase 1: AWS側準備（Mac/ブラウザで実施）

#### Step 1-1: AWSアカウント作成

1. https://aws.amazon.com/jp/ にアクセス
2. 「無料アカウントを作成」をクリック
3. メールアドレス・パスワード・連絡先・クレカ情報を登録
4. 電話番号認証を完了
5. サポートプラン: 「ベーシックサポート（無料）」を選択

#### Step 1-2: IAMユーザー作成

1. AWSコンソール → 「IAM」を検索
2. 左メニュー「ユーザー」→「ユーザーを作成」
3. ユーザー名: `jarvis-backup`
4. 「コンソールアクセスを有効化」は **チェックなし**（プログラム専用）
5. 「次へ」

#### Step 1-3: 権限ポリシーをアタッチ

1. 「許可のオプション」→「ポリシーを直接アタッチ」
2. 「ポリシーの作成」をクリック（新しいタブで開く）
3. 「JSON」タブを選択
4. このディレクトリの `iam-policy.json` の内容をコピー&ペースト
5. ポリシー名: `JarvisBackupS3Policy`
6. 「ポリシーの作成」をクリック
7. 元のタブに戻り、作成した `JarvisBackupS3Policy` を選択
8. 「次へ」→「ユーザーの作成」

#### Step 1-4: アクセスキー発行

1. 作成したユーザー `jarvis-backup` をクリック
2. 「セキュリティ認証情報」タブ
3. 「アクセスキーを作成」
4. 用途: 「コマンドラインインターフェイス (CLI)」
5. 「アクセスキーを作成」
6. **重要**: 表示されるアクセスキーIDとシークレットアクセスキーを控える
   （シークレットはこの画面でしか表示されません）
7. .csvダウンロードを推奨

⚠️ **アクセスキーは絶対にGitHubやSlackに貼り付けないこと！**

---

### Phase 2: VPS側セットアップ

#### Step 2-1: 最新コードを取得

```bash
ssh ubuntu@49.212.137.46
cd astro-webapp
git pull origin main
```

#### Step 2-2: AWS CLIインストール

```bash
sudo apt update
sudo apt install -y awscli
aws --version  # 動作確認
```

#### Step 2-3: AWS認証情報を設定

```bash
aws configure
```

入力項目:
```
AWS Access Key ID: （Phase 1-4で控えたキー）
AWS Secret Access Key: （Phase 1-4で控えたシークレット）
Default region name: ap-northeast-1
Default output format: json
```

確認:
```bash
aws sts get-caller-identity
# 結果に「jarvis-backup」が表示されればOK
```

#### Step 2-4: セットアップスクリプト実行

```bash
bash scripts/aws-setup/setup-s3-backup.sh
```

このスクリプトが以下を自動実行します:
1. S3バケット `jarvis-crm-backups` を作成
2. サーバーサイド暗号化（AES-256）を有効化
3. パブリックアクセスを完全ブロック
4. バージョニング有効化（誤削除対策）
5. HTTPS強制ポリシー適用
6. 90日後の自動削除ルール設定
7. アップロード/削除のテスト実行

#### Step 2-5: 手動バックアップテスト

```bash
# まず通常バックアップを実行
bash scripts/backup.sh

# S3に転送
bash scripts/backup_to_s3.sh
```

成功すると以下のような出力:
```
=== S3バックアップ転送開始: ... ===
  転送対象: jarvis_db_2026-04-XX_03-00-00.sql.gz
  S3にアップロード中...
  OK: サイズ一致（XXX bytes）
  古いバックアップを削除中（90日以上前）...
=== S3バックアップ転送完了: ... ===
```

#### Step 2-6: cron登録

```bash
crontab -e
```

以下を追加:
```cron
# Jarvis CRM 日次バックアップ
0 3 * * * /home/ubuntu/astro-webapp/scripts/backup.sh >> /var/log/jarvis_backup.log 2>&1
30 3 * * * /home/ubuntu/astro-webapp/scripts/backup_to_s3.sh >> /var/log/s3_backup.log 2>&1
```

実行スケジュール:
- **3:00 AM**: ローカルバックアップ作成
- **3:30 AM**: S3に転送（30分の余裕でローカル完了を確実に待つ）

#### Step 2-7: 動作確認

翌日の朝、ログを確認:
```bash
tail -50 /var/log/jarvis_backup.log
tail -50 /var/log/s3_backup.log
```

S3コンソールでも確認:
https://s3.console.aws.amazon.com/s3/buckets/jarvis-crm-backups

---

## トラブルシューティング

### エラー: "An error occurred (AccessDenied) when calling the PutObject operation"

→ IAMポリシーが正しく設定されていません。`iam-policy.json` を再確認してください。

### エラー: "Could not connect to the endpoint URL"

→ リージョンが間違っています。`aws configure` で `ap-northeast-1` に設定し直してください。

### エラー: "BucketAlreadyExists"

→ S3バケット名は世界中で一意である必要があります。既に他の人が `jarvis-crm-backups` を使っている場合は、`backup_to_s3.sh` の `S3_BUCKET` 変数と `setup-s3-backup.sh` の `BUCKET_NAME` を別の名前（例: `jarvis-crm-backups-yourname`）に変更してください。

### バックアップサイズが想定より大きい

→ 顧客データが増えたため。S3コストも増えますが、月額数十円〜数百円の範囲なら許容範囲です。100GB超えるなら、Glacier Deep Archiveへの移行を検討してください（コスト1/4以下）。

---

## 復旧手順（DR: Disaster Recovery）

VPS全損時の復旧手順:

```bash
# 1. 新VPSにAWS CLIをインストール
sudo apt install -y awscli

# 2. 認証情報を設定（同じIAMキー使用）
aws configure

# 3. 最新バックアップをダウンロード
LATEST=$(aws s3 ls s3://jarvis-crm-backups/postgres-backups/ | sort | tail -1 | awk '{print $4}')
aws s3 cp s3://jarvis-crm-backups/postgres-backups/$LATEST /tmp/

# 4. 既存のrestore.shで復元
bash scripts/restore.sh /tmp/$LATEST
```

詳細は `docs/B-09_restore_test_procedure.md` を参照。

---

## セキュリティ設計のポイント

このセットアップでは以下のセキュリティ対策を実装しています:

| 対策 | 内容 | 効果 |
|------|------|------|
| 最小権限IAM | バケット操作のみ許可 | キー漏洩時の被害最小化 |
| サーバー暗号化 | AES-256で保管時暗号化 | 物理ディスク盗難対策 |
| HTTPS強制 | 通信時暗号化を必須化 | 中間者攻撃防止 |
| パブリックアクセスブロック | 全方位で公開禁止 | 設定ミスによる漏洩防止 |
| バージョニング | 削除しても復元可能 | ランサムウェア・誤削除対策 |
| 90日自動削除 | 不要データの自動消去 | コスト最適化＋GDPR対応 |
