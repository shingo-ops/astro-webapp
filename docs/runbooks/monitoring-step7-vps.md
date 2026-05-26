# 監視スタック STEP 7 VPS 操作手順

> **担当**: しんごさん（PO）のみ実施可能な本番操作  
> **実施タイミング**: PR #（STEP 7）が develop にマージされた後

---

## 事前確認

```bash
# VPS に SSH ログイン後、作業ディレクトリへ移動
cd /path/to/salesanchor  # 実際のパスに変更

# 最新コードを取得
git pull origin develop
```

---

## 手順 1: `.env` に監視変数を追加

`.env` ファイルに以下を追記（未設定の項目のみ）:

```bash
# 監視・運用基盤
GRAFANA_USER=admin
GRAFANA_PASSWORD=<強いパスワードに変更>
SLACK_WEBHOOK_URL=https://hooks.slack.com/services/XXXXX/YYYYY/ZZZZZ
UPTIME_KUMA_API_KEY=<Uptime KumaのUIで生成したAPIキー>
```

> **GRAFANA_PASSWORD** の変更が必要な場合は下記「パスワード変更」セクションを参照

---

## 手順 2: Uptime Kuma で API キーを生成

1. `https://app.salesanchor.jp/status/` にアクセス
2. ログイン → 右上アイコン → **API Keys**
3. **Add API Key** → 名前: `prometheus-scrape` → 生成
4. 表示されたキーを `.env` の `UPTIME_KUMA_API_KEY=` に設定

---

## 手順 3: Slack Webhook URL を設定

1. Slack ワークスペースの **Apps** → Incoming Webhooks を開く
2. 既存の Webhook URL を確認するか、新規作成
3. 通知先チャンネル（例: `#alerts-production`）を選択
4. URL を `.env` の `SLACK_WEBHOOK_URL=` に設定

---

## 手順 4: Prometheus と Grafana を再起動

```bash
# 設定を反映（イメージ pull 不要）
docker compose restart prometheus grafana

# 起動確認（healthy になるまで待つ）
docker compose ps prometheus grafana
```

期待される出力:
```
NAME         STATUS
prometheus   Up X minutes (healthy)
grafana      Up X minutes (healthy)
```

---

## 手順 5: Grafana ダッシュボードをインポート

1. `https://app.salesanchor.jp/grafana/` にアクセス
2. 左メニュー → **Dashboards** → **Import**
3. **Dashboard ID: 18278** を入力 → **Load**
4. Data source: **Prometheus** を選択 → **Import**

---

## 手順 6: Slack 通知テスト

1. Grafana → **Alerting** → **Contact points**
2. `slack-ops` の **Test** ボタンをクリック
3. Slack の指定チャンネルにテストメッセージが届くことを確認

---

## パスワード変更（オプション）

```bash
# Grafana 管理者パスワードを変更する場合
docker compose exec grafana grafana-cli admin reset-admin-password <新しいパスワード>
```

---

## ロールバック

問題が発生した場合:

```bash
# 設定を元に戻す
git revert HEAD
git push origin develop

# コンテナを再起動
docker compose restart prometheus grafana
```

---

## 完了確認チェックリスト

- [ ] `docker compose ps` で prometheus・grafana が `(healthy)` 表示
- [ ] `https://app.salesanchor.jp/grafana/api/health` が `{"database":"ok"}` を返す
- [ ] Grafana → Contact points に `slack-ops` が表示されている
- [ ] Slack テスト通知が届いた
- [ ] Dashboard ID 18278 がインポートされている
