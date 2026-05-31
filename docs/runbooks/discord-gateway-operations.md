# Discord Gateway Operations (ADR-009 M3 / Sprint 5)

spec.md v1.1 F5 / Sprint 5 で導入された Discord Bot Gateway (M3 段階) の運用ガイド。

## 起動方法 (開発フェーズ)

```bash
# backend repo root から
cd backend
python -m app.discord_gateway.main
```

環境変数 `DISCORD_BOT_TOKEN_<TENANT_ID>` を 1 つ以上設定する。

```bash
# tenant_006 用 Bot Token (撮影 / QA テナント)
export DISCORD_BOT_TOKEN_TENANT_006=Mxxxxxxxxxxxxxxxxxxxxxxxx
# 任意: テナントコード上書き
export DISCORD_TENANT_CODE_6=tenant-review
```

複数テナント同時起動も可能 (`DISCORD_BOT_TOKEN_4`, `DISCORD_BOT_TOKEN_6`, ...)。

## VPS systemd unit (Sprint 5 以降、しんごさん引き受け)

`/etc/systemd/system/sales-anchor-discord-gateway.service`:

```ini
[Unit]
Description=Sales Anchor Discord Bot Gateway (ADR-009 M3)
After=network.target postgresql.service
Wants=postgresql.service

[Service]
Type=simple
User=ubuntu
WorkingDirectory=/opt/sales-anchor/backend
EnvironmentFile=/etc/sales-anchor/discord-gateway.env
ExecStart=/opt/sales-anchor/venv/bin/python -m app.discord_gateway.main
Restart=on-failure
RestartSec=10
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
```

`/etc/sales-anchor/discord-gateway.env` (権限 0600):

```
DISCORD_BOT_TOKEN_TENANT_006=...
DATABASE_URL=postgresql+asyncpg://...
DISCORD_GATEWAY_LOG_LEVEL=INFO
ADMIN_NOTIFICATION_DISCORD_WEBHOOK=https://discord.com/api/webhooks/...
GEMINI_API_KEY=...
```

起動:

```bash
sudo systemctl daemon-reload
sudo systemctl enable sales-anchor-discord-gateway
sudo systemctl start sales-anchor-discord-gateway
sudo journalctl -u sales-anchor-discord-gateway -f
```

## 動作確認 (実 Discord guild が利用可能になったら)

1. `public.supplier_discord_routing` に対象 guild_id / channel_id を 1 行登録
   (`/super-admin/masters` → 仕入元タブ → Discord 紐付け で UI 操作可能)
2. 該当 channel に「リザードン eX SAR 2枚 @18000円」など投稿
3. `public.discord_inbound_messages` を SELECT して 5 秒以内に 1 行追加されることを確認
4. parse_status が `pending` → `parsed_rule_only` / `parsed_llm` / `unparsed` に
   遷移することを確認 (非同期 task)
5. `/super-admin/inbound` ページを開き、新着メッセージが時系列降順で表示されることを確認

## トラブルシュート

### LoginFailure (致命的)
- Bot Token が失効または不正
- Discord Developer Portal で Token を再発行 → GitHub Secrets を更新 → env を再ロード

### 連続再起動 (最大 10 回で停止)
- `_MAX_RECONNECT_ATTEMPTS = 10` 超過で停止し、`RuntimeError` を投げる
- journalctl を確認、Token 確認後に `systemctl restart` で復旧

### ignored_routing が多発
- supplier_discord_routing の登録漏れ → /super-admin/masters → 仕入元 → Discord 紐付けで追加
- 既存 ignored_routing 行はそのまま (audit ログとして残す)

### parse_status='unparsed' (LLM 失敗)
- `inventory_parser_llm.py` の Gemini API キー (`GEMINI_API_KEY`) を確認
- `public.tenant_llm_budgets` の `current_month_usd` が `monthly_budget_usd` に到達していないか確認
  (到達時は `budget_exhausted` 状態に遷移する)

---

## 顧客 DM 受信箱（Discord ↔ Sales Anchor 受信箱連携）

### 概要

仕入元 Guild メッセージ（在庫処理）とは独立した、顧客向け DM 送受信経路。
`message.guild is None` な DM のみがこの経路に流れる。

```
顧客（Discord DM）
  → discord-gateway-1: client.py on_message
    → _process_dm_message()
      → dm_writer.upsert_lead_and_message()
        → {schema}.leads (source='discord:<user_id>')
        → {schema}.meta_messages (platform='discord', direction='inbound')

スタッフ（受信箱 UI）
  → POST /api/v1/leads/{id}/messages
    → leads.py::_send_discord_message()
      → discord_sender.send_discord_dm()
        → Discord REST API v10 (httpx)
```

### 受信確認

```bash
# DB で直近 Discord DM 受信を確認 (tenant_004 例)
docker exec -i astro-webapp-postgres-1 psql -U jarvis -d jarvis_db <<'SQL'
SELECT id, lead_id, sender_name, message_text, created_at
FROM tenant_004.meta_messages
WHERE platform = 'discord' AND direction = 'inbound'
ORDER BY created_at DESC LIMIT 10;
SQL

# lead が生成されているか確認
docker exec -i astro-webapp-postgres-1 psql -U jarvis -d jarvis_db <<'SQL'
SELECT id, customer_name, source, discord_user_id, discord_dm_channel_id
FROM tenant_004.leads
WHERE source LIKE 'discord:%'
ORDER BY created_at DESC LIMIT 10;
SQL
```

### 送信が 409 になる場合

`discord_dm_channel_id` が leads テーブルに未設定。顧客から先に DM を送ってもらう必要がある。

```bash
# 確認: dm_channel_id が NULL かどうか
docker exec -i astro-webapp-postgres-1 psql -U jarvis -d jarvis_db <<'SQL'
SELECT id, source, discord_user_id, discord_dm_channel_id
FROM tenant_004.leads WHERE source LIKE 'discord:%';
SQL
```

顧客が Bot に DM を送信すると `dm_writer` が自動設定する。

### 送信が 502 になる場合

1. `DISCORD_BOT_TOKEN_{TENANT_ID}` が VPS 環境変数に設定されているか確認
2. Discord Developer Portal で Bot Token が失効していないか確認
3. Gateway コンテナが起動していない → `sudo systemctl restart sales-anchor-discord-gateway`

```bash
# VPS でトークン確認（値は表示しない）
sudo grep -c "DISCORD_BOT_TOKEN" /etc/sales-anchor/discord-gateway.env
```

### dm_writer が失敗する場合（Gateway ログ確認）

```bash
sudo journalctl -u sales-anchor-discord-gateway --since "1 hour ago" | grep "\[dm_writer\]"
```

エラーパターン:
- `lead 取得失敗` → DB 接続エラーまたはスキーマ不整合（migration 091 適用漏れを疑う）
- `duplicate discord_message_id` → 正常（冪等処理。重複受信は Skip される）

### migration 適用漏れチェック

```bash
# tenant_004.leads に discord カラムが存在するか
docker exec -i astro-webapp-postgres-1 psql -U jarvis -d jarvis_db <<'SQL'
SELECT column_name FROM information_schema.columns
WHERE table_schema='tenant_004' AND table_name='leads'
AND column_name IN ('discord_user_id','discord_dm_channel_id');
SQL

# meta_messages に discord インデックスがあるか
docker exec -i astro-webapp-postgres-1 psql -U jarvis -d jarvis_db <<'SQL'
SELECT indexname FROM pg_indexes
WHERE schemaname='tenant_004' AND tablename='meta_messages'
AND indexname='idx_meta_messages_discord';
SQL
```

---

## 関連 ADR / Memory

- ADR-009 Discord Gateway (M2 → M3 拡張)
- spec.md F5 AC5.1-5.5
- backend/app/discord_gateway/inbound_writer.py
- backend/app/services/discord_notifier.py (LLM 予算超過通知、1h de-bounce)
- migration 066 (tenant_llm_budgets seed + last_hard_stop_notified_at)
- memory: project_jarvis_discord_channel_access_pending (Discord アクセス権の現状)
