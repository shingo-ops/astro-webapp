# Environment Variables Reference

| 項目 | 内容 |
|---|---|
| ステータス | Phase 1-D Sprint 7 で初版整備 |
| 作成日 | 2026-04-30 |
| 対象 | VPS (.env) / docker-compose.yml / GitHub Actions |
| 関連 | `.env.example`, `docker-compose.yml`, `docs/PHASE_1D_META_INBOX_OVERVIEW.md` |

このドキュメントは Sales Anchor が利用する環境変数を **用途・必須/任意・生成手順・運用注意** とともにまとめたもの。新規メンバーが VPS に環境を立てる際のリファレンスとして利用する。

---

## 0. 全体方針

- **値の保管**: すべて GitHub Secrets（本番）またはローカル `.env`（開発）に保管。リポジトリには平文で含めない
- **本番投入**: VPS の `/home/ubuntu/jarvis/.env` に直接書き込み。git にはコミットしない（`.gitignore` 済）
- **テンプレート**: `.env.example` にキー名と用途コメントのみを記載（値は空 or プレースホルダ）
- **CI**: GitHub Actions では Secret に登録した値を `.env` に展開してから docker compose を起動

---

## 1. PostgreSQL

| 変数名 | 必須 | 用途 | 例 |
|---|---|---|---|
| `POSTGRES_DB` | ✅ | DB 名 | `myapp_db` |
| `POSTGRES_USER` | ✅ | DB ユーザー名 | `myapp_user` |
| `POSTGRES_PASSWORD` | ✅ | DB パスワード | (32 文字以上のランダム文字列) |
| `DATABASE_URL` | ✅ | SQLAlchemy 接続 URL | `postgresql+asyncpg://myapp_user:<pass>@postgres:5432/myapp_db` |

**生成**: `openssl rand -base64 32` でパスワード生成。

**運用注意**: パスワード変更時は `docker compose down && docker volume rm jarvis_postgres_data` の覚悟が必要（既存データは pg_dump でバックアップ）。

---

## 2. Firebase / Google Identity Platform

| 変数名 | 必須 | 用途 |
|---|---|---|
| `GCP_PROJECT_ID` | ✅ | GCP プロジェクト ID |
| `FIREBASE_API_KEY` | ✅ | Firebase Web API キー |
| `FIREBASE_AUTH_DOMAIN` | ✅ | Auth ドメイン（ADR-032 により `auth.salesanchor.jp`） |
| `GOOGLE_APPLICATION_CREDENTIALS` | ✅ | Service Account JSON のパス |

**生成**: Firebase Console から取得。Service Account JSON は GCP IAM で発行。

**運用注意**:
- Service Account JSON は **GitHub Secrets に保管 + VPS の `/app/firebase-credentials.json` に配置**。git に含めない。
- `FIREBASE_AUTH_DOMAIN` は ADR-032 で `auth.salesanchor.jp`（カスタム認証ドメイン）に切替済。旧値 `sales-ops-with-claude.firebaseapp.com` は Firebase Authorized domains に並行残置されているため、トラブル時は env を旧値に戻すだけで切り戻し可能（再ビルド要）。
- カスタム認証ドメインの初期セットアップ手順は `docs/FIREBASE_CUSTOM_AUTH_DOMAIN_SETUP.md` 参照。

---

## 3. Vite (frontend ビルド時)

| 変数名 | 必須 | 用途 |
|---|---|---|
| `VITE_FIREBASE_API_KEY` | ✅ | frontend に焼き込まれる Firebase API キー（FIREBASE_API_KEY と同値） |
| `VITE_FIREBASE_AUTH_DOMAIN` | ✅ | frontend に焼き込まれる Auth ドメイン（ADR-032 により `auth.salesanchor.jp`） |
| `VITE_GCP_PROJECT_ID` | ✅ | frontend に焼き込まれる GCP プロジェクト ID |

**運用注意**:
- 未設定だと frontend が `auth/invalid-api-key` で真っ白画面。docker compose build 前に必ず確認。
- `VITE_FIREBASE_AUTH_DOMAIN` を変更した場合は frontend コンテナを **再ビルド**しないと反映されない（Vite の `import.meta.env` はビルド時埋め込みのため）。切り戻しも同様に再ビルドが必要。

---

## 4. Redis / Celery

| 変数名 | 必須 | 用途 |
|---|---|---|
| `REDIS_PASSWORD` | ✅ | Redis 認証パスワード |
| `REDIS_URL` | ✅ | アプリ汎用 Redis URL（DB 0） |
| `CELERY_BROKER_URL` | ✅ | Celery broker（DB 1） |
| `CELERY_RESULT_BACKEND` | ✅ | Celery 結果（DB 2） |

**生成**: `openssl rand -base64 32`

**運用注意**: Phase 1-D の OAuth state（`meta_oauth_state:<state>`）は DB 0 に保存される。Redis を再起動すると進行中の OAuth フローは消える（TTL 10 分なので影響軽微）。

---

## 5. アプリケーション基本

| 変数名 | 必須 | 用途 | 例 |
|---|---|---|---|
| `ENVIRONMENT` | ✅ | 環境名 | `production` / `development` |
| `ALLOWED_ORIGINS` | ✅ | CORS 許可オリジン（カンマ区切り） | `https://app.salesanchor.jp,https://salesanchor.jp` |
| `PUBLIC_BASE_URL` | ✅ | LP / 公開ページの base URL | `https://salesanchor.jp` |
| `FRONTEND_BASE_URL` | optional | OAuth callback 後の redirect 先 | `https://app.salesanchor.jp` |

**運用注意**: `PUBLIC_BASE_URL` は B1-B7 Data Deletion Status URL の生成に使用。誤設定すると Status URL が壊れて Meta 審査に影響。

---

## 6. SMTP (B6 Data Deletion 完了メール)

| 変数名 | 必須 | 用途 | 例 |
|---|---|---|---|
| `SMTP_HOST` | optional | SMTP サーバー | `smtp.sendgrid.net` |
| `SMTP_PORT` | optional | SMTP ポート | `587` |
| `SMTP_USER` | optional | SMTP ユーザー | `apikey` |
| `SMTP_PASSWORD` | optional | SMTP パスワード | (SendGrid API key) |
| `MAIL_FROM` | optional | 差出人 | `support@salesanchor.jp` |

**運用注意**: 未設定なら idle（ログのみ）。Meta App Review はメール必須ではないので最小構成可。

---

## 7. Meta Webhook（既存、Phase 2 から）

| 変数名 | 必須 | 用途 |
|---|---|---|
| `META_VERIFY_TOKEN` | ✅ | Webhook 検証トークン（hub.verify_token） |

**生成**: `openssl rand -hex 32` でランダム文字列。Meta Developer Portal の Webhook 設定と一致させる。

**運用注意**: 変更時は Meta Developer Portal 側も同時更新。整合性が崩れると subscribe 失敗。

---

## 8. Meta Inbox（Phase 1-D 新規）

### 8-1. `METADATA_FERNET_KEY`（必須）

| 項目 | 内容 |
|---|---|
| 必須 | ✅ |
| 用途 | Page Access Token と OAuth state の Fernet 暗号化鍵 |
| 形式 | 32 bytes urlsafe base64（44 文字） |
| 例 | `1234abcd...` |

**生成**:

```bash
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

**運用注意**:
- GitHub Secrets に必ず保管。**鍵を紛失すると DB に保存された全 Page Access Token が永遠に復号できなくなる**（再 OAuth が必要）。別の安全な場所にもバックアップを保持すること
- 鍵をローテートする際は、新旧両方の鍵で復号 → 新鍵で再暗号化する移行スクリプトが必要（Phase 1-E 候補）
- コードや Slack に貼り付けない。VPS の `.env` のみ
- backend 起動時に未設定だと warning ログ。`ENFORCE_METADATA_FERNET_KEY=1` を併設すると fail-fast で起動拒否

### 8-2. `META_APP_ID`（必須）

| 項目 | 内容 |
|---|---|
| 必須 | ✅ |
| 用途 | Facebook App ID（OAuth client_id） |
| 例 | `1234567890123456` |

**取得**: Meta Developer Portal の App Settings → Basic → App ID。

**運用注意**: 公開しても問題ないが、運用上 GitHub Secrets に保管推奨。Test Mode と本番モードで App は同一（モード切替のみ）。

### 8-3. `META_APP_SECRET`（必須、既存）

| 項目 | 内容 |
|---|---|
| 必須 | ✅ |
| 用途 | App Secret（HMAC 検証 + OAuth code 交換 + Page Access Token 長期化） |

**取得**: Meta Developer Portal の App Settings → Basic → App Secret。

**運用注意**:
- **絶対に公開しない**。GitHub Secrets で管理必須
- 漏洩した場合は即座に Reset Secret + 全 Page Access Token を再 OAuth 取得
- Sprint 1 までは webhook.py の HMAC 検証用途のみ。Sprint 2 で OAuth で追加利用

### 8-4. `META_OAUTH_REDIRECT_URI`（必須）

| 項目 | 内容 |
|---|---|
| 必須 | ✅ |
| 用途 | Facebook Login の redirect_uri |
| 例 | `https://app.salesanchor.jp/channels/oauth/callback` |

**運用注意**:
- Meta Developer Portal の **Valid OAuth Redirect URIs** に同じ URL を登録すること
- 開発環境では `http://localhost:5173/channels/oauth/callback` を Meta 側にも登録 + 本変数を切替
- 本番ドメイン変更時は Meta Developer Portal も同時更新

### 8-5. `META_GRAPH_API_VERSION`

| 項目 | 内容 |
|---|---|
| 必須 | ✅ |
| 用途 | Graph API バージョン |
| 既定 | `v19.0` |

**運用注意**:
- Meta は約 3 ヶ月ごとに新バージョンをリリース、24 ヶ月で deprecate
- 環境変数化により破壊的変更時の切替が容易
- アップグレード時は staging で全 endpoint を疎通確認してから本番反映

### 8-6. `META_PAGE_ID`（レガシー、廃止予定）

| 項目 | 内容 |
|---|---|
| 必須 | ⚠ |
| 用途 | 単一テナント時代の Page ID 直読み（後方互換用 fallback） |

**運用注意**:
- Phase 1-D では Sprint 6 で `tenant_meta_config` 由来テナント特定が主、これは fallback として残置
- **Phase 1-E（次フェーズ）で削除予定**（spec §14 Q6 の暫定方針）

### 8-7. `ENFORCE_METADATA_FERNET_KEY`

| 項目 | 内容 |
|---|---|
| 必須 | optional |
| 用途 | "1" で起動時 Fernet 鍵検証で fail-fast |
| 既定 | 未設定（warning ログのみ） |

**運用注意**:
- 本番では **"1" を推奨**。誤って未設定でデプロイすると暗号化全機能が黙って失敗するため
- ローリング更新時は warning モード → fail-fast に切り替えるとリスク低い

---

## 9. Google Calendar 連携

| 変数名 | 必須 | 用途 |
|---|---|---|
| `GOOGLE_CALENDAR_CLIENT_ID` | ✅ | OAuth 2.0 クライアント ID |
| `GOOGLE_CALENDAR_CLIENT_SECRET` | ✅ | OAuth 2.0 クライアントシークレット |
| `GOOGLE_CALENDAR_REDIRECT_URI` | ✅ | OAuth コールバック URL |

**取得**: [Google Cloud Console](https://console.cloud.google.com/auth/clients?project=sales-ops-with-claude) > `salesanchor-calendar` クライアント。

**運用注意**:
- `GOOGLE_CALENDAR_CLIENT_SECRET` は Google Console で一度しか表示されない。**発行直後に Bitwarden へ保存必須**
- `GOOGLE_CALENDAR_REDIRECT_URI` は `https://api.salesanchor.jp/api/v1/google-calendar/connect/callback` に固定
- `METADATA_FERNET_KEY` は Meta Inbox と共用（既存設定を流用）
- GitHub Secrets に `GOOGLE_CALENDAR_CLIENT_SECRET` を登録済み（deploy 時に自動注入）

---

## 10. Discord Gateway Worker (ADR-009)

| 変数名 | 必須 | 用途 |
|---|---|---|
| `DISCORD_GATEWAY_LOG_LEVEL` | optional | ログレベル | `INFO` / `DEBUG` |
| `DISCORD_BOT_TOKEN_<tenant_id>` | optional | per-tenant Bot Token |
| `DISCORD_TENANT_CODE_<tenant_id>` | optional | テナント表示名 |

**運用注意**:
- 例: tenant_004 = HIGH LIFE JPN なら `DISCORD_BOT_TOKEN_4`
- 未設定時は idle 待機（接続せず）
- Bot Token は Discord 開発者ポータルで取得、GitHub Secrets に保管

---

## 11. デプロイ前 / 撮影前のチェック

| カテゴリ | チェック項目 |
|---|---|
| PostgreSQL | DATABASE_URL が PostgreSQL を指している（SQLite ではない） |
| Firebase | VITE_* と非 VITE 系の値が一致 |
| Firebase | `FIREBASE_AUTH_DOMAIN` / `VITE_FIREBASE_AUTH_DOMAIN` が `auth.salesanchor.jp`（ADR-032 切替後）or 切り戻し中なら `sales-ops-with-claude.firebaseapp.com` |
| Firebase | Firebase Console > Authentication > Settings > Authorized domains に `auth.salesanchor.jp` と旧ドメインの両方が登録されている |
| Firebase | Meta Developer Portal > Facebook Login > Valid OAuth Redirect URIs に `https://auth.salesanchor.jp/__/auth/handler` と旧 `https://sales-ops-with-claude.firebaseapp.com/__/auth/handler` の両方が残置されている |
| Redis | パスワード設定済 |
| Meta | METADATA_FERNET_KEY、META_APP_ID、META_APP_SECRET、META_OAUTH_REDIRECT_URI すべて注入済 |
| Google Calendar | GOOGLE_CALENDAR_CLIENT_SECRET が GitHub Secrets に登録済み |
| Meta | META_OAUTH_REDIRECT_URI と Meta Developer Portal の Valid OAuth Redirect URIs が一致 |
| Meta | META_GRAPH_API_VERSION が運用版に合致（v19.0 等） |
| Webhook | META_VERIFY_TOKEN が Meta Developer Portal と一致 |
| Public | PUBLIC_BASE_URL が `https://salesanchor.jp` |
| Public | FRONTEND_BASE_URL が `https://app.salesanchor.jp` |
| 起動確認 | `docker compose logs backend` に Fernet 関連 error がない |
| 起動確認 | `/api/v1/health` が 200 |
| 起動確認 | `/openapi.json` に meta/conversations/messages のパスが含まれる |

---

## 12. 関連ドキュメント

- 仕様書本体: `.claude-pipeline/spec.md`
- `.env.example`: 全変数のテンプレート
- Phase 1-D 全体ドキュメント: `docs/PHASE_1D_META_INBOX_OVERVIEW.md`
- 撮影前チェックリスト: `docs/META_APP_REVIEW_PRE_RECORDING_CHECKLIST.md`
- B1-B7 Data Deletion 設計: `docs/data_deletion_callback_design.md`
- Discord Gateway 設計: `docs/ADR-009_discord_gateway.md`
