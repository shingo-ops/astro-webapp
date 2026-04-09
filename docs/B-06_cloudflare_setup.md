# B-6: Cloudflare プロキシオン設定手順

## 対象: jarvis-claude.uk
## 最終更新: 2026-04-06

---

## 目的

Cloudflareのプロ���シ機能（オレンジ雲）を有効化し、WAF・DDoS Protectionを有効にする。
現在はプロキシオフ（グレー雲）のため、VPSのIPが直接公開されている。

---

## 手順

### Step 1: Cloudflareダッシュボードにログイン

1. https://dash.cloudflare.com にログイン
2. ドメイン `jarvis-claude.uk` を選択

### Step 2: DNSレコードのプロキシ有効化

1. **DNS** > **Records** を開く
2. `jarvis-claude.uk` のAレコード（49.212.137.46）を確認
3. 「プロキシステータス」のアイコンをクリックし、**オレンジ���（プロキシ済み）** に変更
4. **Save** をクリック

### Step 3: SSL/TLSモードを Full (Strict) に変更

1. **SSL/TLS** > **Overview** を開く
2. ���ードを **Full (Strict)** に変更
   - Full (Strict): Cloudflare ↔ VPS間もSSL（Let's Encrypt証明書を検証）
   - これにより、Cloudflare ↔ VPS間の通信も暗号化・検証される

### Step 4: WAF設定

1. **Security** > **WAF** を開く
2. **Managed Rules** を有効化
   - Cloudflare OWASP Core Ruleset: ON
   - Cloudflare Managed Ruleset: ON
3. 必要に応じてカスタムルールを追加

### Step 5: DDoS Protection確認

1. **Security** > **DDoS** を開く
2. HTTP DDoS attack protection: 有効（デフォルトON）
3. Network-layer DDoS attack protection: 有効（デフォルトON）

### Step 6: Bot Fight Mode

1. **Security** > **Bots** を開く
2. **Bot Fight Mode**: ON

### Step 7: Nginx設定の更新

Cloudflareプロキシ経由のため、クライアントの本当のIPは `CF-Connecting-IP` ヘッダーに入る。

```nginx
# nginx/nginx.conf に追加（既存のreal_ip設定を更新）
set_real_ip_from 103.21.244.0/22;
set_real_ip_from 103.22.200.0/22;
set_real_ip_from 103.31.4.0/22;
set_real_ip_from 104.16.0.0/13;
set_real_ip_from 104.24.0.0/14;
set_real_ip_from 108.162.192.0/18;
set_real_ip_from 131.0.72.0/22;
set_real_ip_from 141.101.64.0/18;
set_real_ip_from 162.158.0.0/15;
set_real_ip_from 172.64.0.0/13;
set_real_ip_from 173.245.48.0/20;
set_real_ip_from 188.114.96.0/20;
set_real_ip_from 190.93.240.0/20;
set_real_ip_from 197.234.240.0/22;
set_real_ip_from 198.41.128.0/17;
real_ip_header CF-Connecting-IP;
```

**注意**: Cloudflare導入後、レート制限の `$binary_remote_addr` が正しくクライアントIPを取得するか確認すること。

---

## 検証

1. IPアドレスが隠蔽されたか確認:
   ```bash
   nslookup jarvis-claude.uk
   # → CloudflareのIPが返ること（49.212.137.46 ではないこと）
   ```

2. HTTPSアク��スが正常か確認:
   ```bash
   curl -I https://jarvis-claude.uk/api/health
   # → cf-ray ヘッダーが含まれること
   ```

3. WAFが動作しているか確認:
   ```bash
   curl "https://jarvis-claude.uk/?q=<script>alert(1)</script>"
   # → 403 or Cloudflareのブロックページが返ること
   ```

---

## 注意事項

- プロキシオン後、VPSのIPが過去にDNSで公開されていた場合、攻撃者がIPを知っている可能性がある
- UFWで22/80/443以外のポートが閉じていることを再確認する
- Let's Encrypt証明書の更新がCloudflare経由でも動作するか確認する
