# インシデント対応 Playbook

## 対象: Jarvis CRM（jarvis-claude.uk）
## 最終更新: 2026-04-06

---

## 1. インシデント検知

以下のいずれかが発生した場合、インシデント対応を開始する:

- Grafanaアラート（CPU/メモリ/DB異常）が発報
- Uptime Kumaからダウン通知
- auth_eventsで異常な認証失敗パターンを検出
- 顧客・ユーザーからの報告
- 外部機関からの連絡（JPCERT/CC等）

---

## 2. 初動対応（発覚から1時間以内）

### Step 1: 被害状況の把握
```bash
# サーバーの状態確認
ssh ubuntu@49.212.137.46
docker compose ps
docker compose logs --tail=100 backend

# 認証ログの確認（直近1時間の認証失敗）
docker compose exec postgres psql -U myapp_user -d myapp_db -c \
  "SELECT event_type, client_ip, COUNT(*) FROM public.auth_events
   WHERE created_at > NOW() - INTERVAL '1 hour'
   GROUP BY event_type, client_ip ORDER BY count DESC;"
```

### Step 2: 影���範囲の特定
```bash
# 不正アクセスのあったテナントを特定
docker compose exec postgres psql -U myapp_user -d myapp_db -c \
  "SELECT DISTINCT schema_name FROM information_schema.schemata
   WHERE schema_name LIKE 'tenant_%';"

# 各テナントのaudit_logsで異常な操作を確認
docker compose exec postgres psql -U myapp_user -d myapp_db -c \
  "SELECT * FROM tenant_001.audit_logs
   WHERE created_at > NOW() - INTERVAL '24 hours'
   ORDER BY created_at DESC LIMIT 50;"
```

### Step 3: 封じ込め
```bash
# 不正なIPアドレスをブロック
sudo ufw deny from <攻撃元IP>

# 侵害されたアカウントを無効化
docker compose exec postgres psql -U myapp_user -d myapp_db -c \
  "UPDATE public.users SET is_active = false WHERE email = '<対象メール>';"

# ��要に応じてサービスを一時停止
docker compose stop backend
```

---

## 3. 調査（発覚から24時間以内）

### Step 4: ログの保全
```bash
# 全コンテナログをバックアップ
docker compose logs > /home/ubuntu/incident_logs_$(date +%Y%m%d%H%M).txt

# DBのバックアップ（証拠保全）
docker compose exec postgres pg_dump -U myapp_user myapp_db | gzip > \
  /home/ubuntu/backups/incident_backup_$(date +%Y%m%d%H%M).sql.gz
```

### Step 5: 侵入経路の特���
- Nginxアクセスログで攻撃パターンを分析
- auth_eventsで認証突破の痕跡を確認
- audit_logsでデータアクセスの範囲を特定

---

## 4. 復旧と報告

### Step 6: 復旧作業
```bash
# パスワード・認証情報のリセット
# Firebase側でも該当ユーザ��のセッション無効化

# サービス再開
docker compose up -d

# ヘルスチェック確認
curl -s https://jarvis-claude.uk/api/health | jq
```

### Step 7: 当局への報告（個人情報漏洩の場合）
**個人情報保護法に基づく報告義務（72時間以内��:**

1. **個人情報保護委員会への報告**
   - 速報: 事態を知った時点から3〜5日以内
   - 確報: 30日以内（不正アクセスの場合は60日以内）
   - 報告先: https://www.ppc.go.jp/personalinfo/legal/leakAction/

2. **本人への通知**
   - 漏洩した個人情報の項目
   - 原因
   - 二次被害のおそれ
   - 対応状況

### Step 8: 再発防止
- インシデント報告書の作成
- 根本原因の分析と対策の実施
- 必要に応じてセキュリ���ィ設定の見��し
- Playbook自体の更新

---

## 緊急連絡先

| 項目 | 連絡先 |
|------|--------|
| サーバー管理 | （担当者名・連絡先を記入） |
| セ��ュリティ担当 | （担当者名・連絡先を記入） |
| 個人情報保護委員会 | https://www.ppc.go.jp/ |
| JPCERT/CC | https://www.jpcert.or.jp/ |
| さくらVPSサポート | https://help.sakura.ad.jp/ |

---

## 判断基準: インシデントの重大度

| レベル | 基準 | 対応 |
|--------|------|------|
| Critical | 個人情報の漏洩確認 | 全手順を即座に実行、72時間以内に当局報告 |
| High | 不正アクセスの痕跡あり | Step 1〜6を実行、漏洩有無を調査 |
| Medium | 大量の認証失敗 | IPブロック + 監視強化 |
| Low | 通常のスキャン・ボット | ログ記録のみ |
