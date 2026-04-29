# Phase 5: ドメイン切替 Runbook

| 項目 | 値 |
|---|---|
| 起票日 | 2026-04-29 |
| 担当 | Hikky-dev（コード）+ しんごさん（VPS / Firebase Console） |
| 戦略 | zero-downtime parallel listen（jarvis-claude.uk と app/api.salesanchor.jp を並行稼働） |
| ロールバック | nginx.conf の新規 server block を削除 + backend `.env` を旧値に戻すだけ |

---

## 0. 前提

しんごさんが以下を完了済みである前提:
- DNS: `app.salesanchor.jp` / `api.salesanchor.jp` が VPS の IP を指している
- SSL: `/etc/letsencrypt/live/app.salesanchor.jp/` および `/etc/letsencrypt/live/api.salesanchor.jp/` に証明書が発行されている

---

## 1. デプロイ手順（VPS 側、しんごさん作業）

### 1-1. SSH 接続
```
ssh ubuntu@49.212.137.46
```

### 1-2. SSL 証明書の存在確認

新ドメインの証明書ディレクトリが存在することを確認:

```
sudo ls /etc/letsencrypt/live/app.salesanchor.jp/
```

期待される出力: `cert.pem  chain.pem  fullchain.pem  privkey.pem  README`

```
sudo ls /etc/letsencrypt/live/api.salesanchor.jp/
```

同上が表示されれば OK。

**もし「No such file or directory」が出たら**: certbot で証明書発行が必要。下記 1-2-A を実施。

#### 1-2-A. 証明書発行（必要な場合のみ、デッドロック回避手順あり）

⚠️ **重要**: PR #184 が既にマージされて nginx.conf に新ドメインの `ssl_certificate` 行が含まれた状態だと、443 リッスン → cert 無し → nginx 起動失敗 → certbot も叩けない、というデッドロックが起きます。

**手順**: ssl 関連行を一旦コメントアウトして HTTP のみで起動 → certbot 発行 → 復活、の 2 段階で進めます。

```
cd /home/ubuntu/salesanchor
```

`nginx/nginx.conf` の以下のブロック内の `ssl_certificate` / `ssl_certificate_key` の 2 行をコメントアウト + `listen 443 ssl;` を一旦削除（or HTTP リダイレクトの 80 ブロックだけ残す）:
- `app.salesanchor.jp` の HTTPS server block（line 165 付近〜）
- `api.salesanchor.jp` の HTTPS server block（line 240 付近〜）

```
docker compose up -d --no-deps nginx
```

certbot で発行（HTTP-01 challenge は :80 経由）:

```
docker compose run --rm certbot certonly --webroot -w /var/www/certbot -d app.salesanchor.jp
```

```
docker compose run --rm certbot certonly --webroot -w /var/www/certbot -d api.salesanchor.jp
```

成功したら `nginx/nginx.conf` のコメントアウト行を元に戻し、再度 nginx を recreate:

```
docker compose up -d --no-deps nginx
```

**事前にしんごさんが certbot で発行済みなら、この手順は不要**。1-3 へ進む。

### 1-3. .env の ALLOWED_ORIGINS 更新

```
cd /home/ubuntu/salesanchor
```

```
grep ALLOWED_ORIGINS .env
```

現状の値を確認した上で、以下のように更新（テキストエディタで .env を編集）:

```
ALLOWED_ORIGINS=https://jarvis-claude.uk,https://app.salesanchor.jp
```

### 1-4. PR デプロイ後の nginx 再作成

GitHub で PR がマージされ、deploy.yml が走った後:

```
cd /home/ubuntu/salesanchor
docker compose up -d --no-deps nginx
```

`-s reload` ではなく **コンテナ再作成** が必須（bind mount の stale inode 問題回避、2026-04-29 知見）。

### 1-5. backend 再起動（ALLOWED_ORIGINS 反映）

```
docker compose up -d --no-deps backend
```

### 1-6. 動作確認

```
curl -sI https://app.salesanchor.jp/api/health
```

200 OK が返れば成功。

```
curl -sI https://api.salesanchor.jp/api/health
```

200 OK が返れば成功。

```
curl -sI https://jarvis-claude.uk/api/health
```

200 OK が返ればフォールバック（旧ドメイン）も維持されている。

---

## 2. Firebase Console 作業（しんごさん作業）

### 2-1. Authorized domains に追加

1. https://console.firebase.google.com/project/sales-ops-with-claude/authentication/settings を開く
2. **Authorized domains** タブ
3. **Add domain** をクリック
4. `app.salesanchor.jp` を追加
5. `api.salesanchor.jp` も追加（API 側で signInWithCustomToken を使う場合）

### 2-2. OAuth リダイレクト URI 追加（IdP 連携している場合のみ）

Google / Twitter / Facebook など IdP を使っている場合:
1. 各 IdP の Console を開く
2. Authorized redirect URIs に以下を追加:
   - `https://app.salesanchor.jp/__/auth/handler`
   - `https://api.salesanchor.jp/__/auth/handler`（必要なら）

---

## 3. 動作検証チェックリスト

| 項目 | 確認方法 | 期待結果 |
|---|---|---|
| `https://app.salesanchor.jp/` でログインできる | ブラウザでアクセス → ログイン | 既存ユーザーで成功 |
| `https://app.salesanchor.jp/api/health` 200 | curl | 200 OK |
| `https://api.salesanchor.jp/api/health` 200 | curl | 200 OK |
| `https://api.salesanchor.jp/` 404 | curl | 404 Not Found（API only なので意図通り） |
| `https://jarvis-claude.uk/` 並行稼働 | ブラウザでアクセス | 既存ユーザーで成功（旧ドメインも生きている） |
| Firebase Auth が新ドメインで動く | app.salesanchor.jp でログイン | エラーなし |
| CSP が新ドメインで違反していない | DevTools Console | CSP 警告なし |

---

## 4. ロールバック手順

切替に問題が出た場合:

### 4-1. backend のみロールバック（CORS だけ問題）

```
cd /home/ubuntu/salesanchor
```

`.env` の `ALLOWED_ORIGINS` を旧値（`https://jarvis-claude.uk`）に戻す。

```
docker compose up -d --no-deps backend
```

### 4-2. nginx 設定もロールバック

PR を revert（GitHub で「Revert」ボタン）→ deploy.yml が走る → nginx が旧 conf に戻る。

または手動:
```
cd /home/ubuntu/salesanchor
git checkout HEAD~1 -- nginx/nginx.conf
docker compose up -d --no-deps nginx
```

---

## 5. 残作業（このフェーズの後）

### しんごさん判断待ち
- [ ] **jarvis-claude.uk の最終的な扱い**: 即停止 / 並行稼働継続 / 永続 301 リダイレクト
  - 即停止 → 旧ドメインの DNS をやめる + nginx server block を削除
  - 永続 301 → `return 301 https://app.salesanchor.jp$request_uri;` に変更
- [ ] **VITE_API_URL 環境変数の追加検討**: 現状 frontend は相対パス `/api/v1` で動くので不要。将来的に API ドメインを完全分離するなら追加

### 旧ドメイン停止前のチェックリスト（jarvis-claude.uk を停止する場合のみ）
- [ ] **Nginx Exporter のターゲット URL** 確認: 旧 `jarvis-claude.uk/nginx_status` を叩いている場合は新ドメイン側に `/nginx_status` location を追加 or Exporter URL を `localhost:80` 経由に切替
- [ ] **B-04 / B-06 / DEVELOPMENT_GUIDE_FOR_SHINGO.md** など docs の `jarvis-claude.uk` 参照を一括更新（別 PR）
- [ ] **Cloudflare 設定**（B-06）が新ドメインに不要なら無効化、必要なら DNS 移行

### Meta App Review 関連の連動作業
- [ ] **C3: Webhook URL 切替**（しんごさん作業、Meta Developer Dashboard）
  - 旧: `https://jarvis-claude.uk/api/v1/webhook/messenger`
  - 新: `https://api.salesanchor.jp/api/v1/webhook/messenger`
  - Phase 5 デプロイ完了後に実施

### docs クリーンアップ
- [ ] 既存 docs（B-04, B-06, FIREBASE_API_KEY_RESTRICTION_GUIDE 等）の `jarvis-claude.uk` 参照更新は別 PR で対応（Phase 5 完了後）

---

## 6. メモ

- Phase 5 PR は **zero-downtime** を最優先。jarvis-claude.uk を「並列で残す」設計
- 切替の心理的負担を分散するため、新ドメインの動作確認 → 周知 → 旧停止判断は順番に実施
- Cloudflare 設定（B-06）は jarvis-claude.uk 経由のみ。salesanchor.jp 系は直 Let's Encrypt で発行されているため、Cloudflare 経由ではない（DNS は さくら DNS or 直 A レコード）
