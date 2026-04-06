# B-9: 月次リストアテスト手順書

## 目的
バックアップから正常に復元できることを月1回確認する。

## 最終更新: 2026-04-06

---

## 実施タイミング
毎月第1月曜日（業務時間外推奨）

---

## 手順

### Step 1: 最新バックアップの確認

```bash
ssh ubuntu@49.212.137.46

# ローカルバックアップの確認
ls -lh /home/ubuntu/backups/postgres/
# → 最新の .gz ファイルがあること���確認

# S3バックアップの確認（B-8導入後）
aws s3 ls s3://jarvis-crm-backups/postgres-backups/ --human-readable | tail -5
```

### Step 2: テスト用DBの作成

```bash
# テスト用データベースを作成
docker compose exec postgres psql -U myapp_user -d postgres -c \
  "CREATE DATABASE restore_test;"
```

### Step 3: バックアップからリストア

```bash
# 最新のバックアップファイルを指定
BACKUP_FILE=$(ls -t /home/ubuntu/backups/postgres/*.gz | head -1)

# リストア実行
gunzip -c "$BACKUP_FILE" | docker compose exec -T postgres \
  psql -U myapp_user -d restore_test
```

### Step 4: データの整合性確認

```bash
docker compose exec postgres psql -U myapp_user -d restore_test -c "
  -- テナント数の確認
  SELECT COUNT(*) AS tenant_count FROM public.tenants;

  -- ユーザー数の確認
  SELECT COUNT(*) AS user_count FROM public.users;

  -- テナントスキーマの確認
  SELECT schema_name FROM information_schema.schemata
  WHERE schema_name LIKE 'tenant_%' ORDER BY schema_name;
"
```

### Step 5: 本番DBとの件数比較

```bash
# 本番DBのテナント数
docker compose exec postgres psql -U myapp_user -d myapp_db -c \
  "SELECT COUNT(*) FROM public.tenants;"

# ���ストアDBのテナント数
docker compose exec postgres psql -U myapp_user -d restore_test -c \
  "SELECT COUNT(*) FROM public.tenants;"

# 件数が一致すればOK
```

### Step 6: テスト用DBの削除

```bash
docker compose exec postgres psql -U myapp_user -d postgres -c \
  "DROP DATABASE restore_test;"
```

---

## 結果記録

| 実施日 | バックアップ日時 | リストア結果 | テナント数一致 | 実施者 |
|--------|-----------------|-------------|--------------|--------|
| YYYY/MM/DD | ファイル名 | OK/NG | OK/NG | 名前 |

---

## リストア失敗時の対応

1. エラーメッセージを記録
2. バックアップファイルの破損チェック: `gunzip -t <file>.gz`
3. 前日のバックアップで再試行
4. S3上のバックアップで再試行
5. 解決しない場合は、バックアップスクリプトの見直し
