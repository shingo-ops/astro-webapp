# ADR-069: Uptime Kuma 監視ダッシュボードの有効化

**Status**: Accepted  
**Date**: 2026-05-25  
**Author**: shingo-ops (PO)  

---

## What（何を・なぜ・ユーザー価値・事業制約）

### 背景

本番環境（さくらVPS）で稼働する salesanchor の以下サービスについて、障害の早期検知体制が存在しなかった。

- 本番アプリ `https://app.salesanchor.jp/`
- API `https://api.salesanchor.jp/`
- LP `https://salesanchor.jp/`
- PostgreSQL / Redis / Celery
- 外部連携（Meta API / Firebase）

問題が発生してもユーザーから報告されるまで気づけない状態であった。

### 決定

**B-3 として docker-compose.yml に定義済みの Uptime Kuma コンテナを有効化**し、`monitor.salesanchor.jp` として公開する。

### スコープ

- `docker-compose.yml`: `uptime-kuma` イメージを `latest` → `2` にピン固定
- `nginx/nginx.conf`: `monitor.salesanchor.jp` サーバーブロックを追加
- 既存アプリへのコード変更: **ゼロ**

### スコープ外（VPS上でのオペレーション・UI操作）

以下は本 PR に含まない。デプロイ後に手動で実施する:

1. Cloudflare DNS: `monitor.salesanchor.jp` A レコード → VPS IP を追加
2. VPS 上で certbot 実行:
   ```bash
   certbot certonly --webroot -w /var/www/certbot -d monitor.salesanchor.jp
   ```
3. Docker コンテナ再起動: `docker compose up -d --no-deps nginx uptime-kuma`
4. Uptime Kuma UI で監視項目を登録（下記参照）
5. Discord Webhook 通知設定
6. 管理者アカウントの 2FA（二段階認証）設定

### 監視対象（UI登録予定）

| 名称 | 種別 | 対象 | 間隔 |
|------|------|------|------|
| App（本番） | HTTP | https://app.salesanchor.jp/ | 30秒 |
| API ヘルスチェック | HTTP | https://api.salesanchor.jp/api/health | 30秒 |
| LP | HTTP | https://salesanchor.jp/ | 60秒 |
| PostgreSQL | TCP | localhost:5432 | 60秒 |
| Redis | TCP | localhost:6379 | 60秒 |
| Meta API | HTTP | https://graph.facebook.com/ | 5分 |
| Firebase | HTTP | https://firebaseio.com/ | 5分 |

### アクセス制御

Uptime Kuma の組み込みログイン認証（ID/パスワード + TOTP 2FA）を使用する。
IP ホワイトリスト方式は採用しない（固定IP が不要で外出先からもアクセス可能）。

---

## Why（採用理由）

- Uptime Kuma は B-3 として既に docker-compose.yml に定義されており、コンテナ追加コストがゼロ
- セルフホスト型のため監視データが外部クラウドに送信されない
- Docker 内部ネットワーク経由で PostgreSQL・Redis などローカルサービスも監視可能（SaaS 型監視では不可能）
- MIT ライセンス・完全無料（UptimeRobot は内部 IP 監視不可、Better Stack は $348/年〜）
- 既存の `/status/` パスとは独立した専用ドメインにすることで Uptime Kuma の SPA が正常動作する
