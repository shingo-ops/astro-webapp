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

## 関連 ADR / Memory

- ADR-009 Discord Gateway (M2 → M3 拡張)
- spec.md F5 AC5.1-5.5
- backend/app/discord_gateway/inbound_writer.py
- backend/app/services/discord_notifier.py (LLM 予算超過通知、1h de-bounce)
- migration 066 (tenant_llm_budgets seed + last_hard_stop_notified_at)
- memory: project_jarvis_discord_channel_access_pending (Discord アクセス権の現状)
