# Phase 1-D: Meta Inbox UI — Implementation Overview

| 項目 | 内容 |
|---|---|
| ステータス | Sprint 1〜6 完了 + Sprint 7（運用ドキュメント整備中） |
| 作成日 | 2026-04-30 |
| 対象 | Meta App Review 提出を目的とした Inbox UI 実装 |
| 仕様書 | `.claude-pipeline/spec.md` |
| 期間 | 2026-04-30 ～（Phase 1-D Sprint 1〜7） |

このドキュメントは Phase 1-D で実装した内容の **全体像** を 1 ファイルにまとめた運用リファレンス。Sprint ごとの詳細は `.claude-pipeline/sprints/sprint-NN/` を参照。

---

## 1. 背景と目的

Sales Anchor は Phase 1-A から Phase 1-C までで CRM のコア機能（マルチテナント、顧客マスタ、商品マスタ、リード/会話 UI）を稼働させてきた。Meta（Facebook Messenger / Instagram）連携は Phase 2 で受信基盤（webhook）と meta_messages テーブルが実装済だったが、**受信メッセージを表示する UI と返信する UI が未実装** で、Meta App Review 提出に必要な 7 シーン撮影が不可能だった。

Phase 1-D は **Meta App Review 通過を最優先** に、Inbox UI の MVP を実装した。

### 1-1. 申請する Permission（6 個 + Human Agent Tag）

| Permission | レベル | 実装で使う場所 |
|---|---|---|
| `pages_show_list` | Standard | OAuth callback で `/me/accounts` 呼出 |
| `pages_manage_metadata` | Standard | `/{page_id}/subscribed_apps` 登録 / 解除 |
| `pages_messaging` | Advanced | Messenger Send API |
| `pages_read_engagement` | Advanced | Messenger 会話履歴の Webhook 受信 |
| `instagram_basic` | Advanced | `/{page_id}?fields=instagram_business_account` |
| `instagram_manage_messages` | Advanced | Instagram Messaging API |
| Human Agent Tag | Feature | 24h-7d で `messaging_type=MESSAGE_TAG, message_tag=HUMAN_AGENT` |

---

## 2. アーキテクチャ図（実装後の構成）

```
┌──────────────────────────┐         ┌──────────────────────────────┐
│  Meta Platform           │         │ Sales Anchor Frontend         │
│  (Facebook / Instagram)  │         │ (app.salesanchor.jp)         │
└────────┬─────────┬───────┘         └──────────────┬───────────────┘
         │         │                                │
         │ Webhook │ OAuth                          │ JWT Auth
         │ POST    │ Redirect                       │ React Router
         │ (HMAC)  │                                │
         ▼         ▼                                ▼
┌─────────────────────────────────────────────────────────────────┐
│  Sales Anchor Backend (api.salesanchor.jp / FastAPI)            │
│                                                                  │
│  ┌──────────────────────┐   ┌──────────────────────────────┐    │
│  │ webhook.py           │   │ meta_inbox.py                │    │
│  │  - Messenger 受信    │   │  - OAuth start/callback/del  │    │
│  │  - Instagram 受信    │   │  - GET /meta/channels        │    │
│  │    (Sprint 6)        │   │  - GET /conversations        │    │
│  │  - tenant 特定:      │   │                              │    │
│  │    tenant_meta_config│   └──────────┬───────────────────┘    │
│  │    page_id 逆引き    │              │                         │
│  └──────────┬───────────┘              │                         │
│             │                          │                         │
│             ▼                          ▼                         │
│  ┌──────────────────────┐   ┌──────────────────────────────┐    │
│  │ leads.py             │   │ services/                    │    │
│  │  - GET /leads/{id}/  │   │  - encryption.py (Fernet)   │    │
│  │    messages          │   │  - meta_graph.py (httpx)    │    │
│  │  - POST /messages    │   │  - messaging_window.py      │    │
│  │  - POST mark-read    │   │    (24h/7d 判定)            │    │
│  └──────────┬───────────┘   └──────────────────────────────┘    │
│             │                                                    │
│             ▼                                                    │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │ PostgreSQL (per-tenant schema, RLS 有効)                 │   │
│  │  - tenant_meta_config (migration 040, 新規)              │   │
│  │  - meta_messages (migration 041 で列拡張)                │   │
│  │  - leads (既存、会話エンティティ兼用)                     │   │
│  │  - permissions (migration 042 で +4 件)                  │   │
│  │  - audit_logs (既存、OAuth/送信失敗を記録)               │   │
│  └──────────────────────────────────────────────────────────┘   │
│                                                                  │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │ Redis (state ストア)                                      │   │
│  │  - meta_oauth_state:<state> (TTL 10 分、Fernet 暗号化)   │   │
│  └──────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────┘
                          │
                          ▼
              ┌───────────────────────────┐
              │ Meta Graph API (v19.0)    │
              │  - /me/accounts           │
              │  - /{page_id}/subscribed_apps │
              │  - /{page_id}/messages    │
              │  - /me/messages (IG DM)   │
              └───────────────────────────┘
```

---

## 3. Sprint 履歴サマリー

| Sprint | テーマ | 主な成果物 | コミット数 | テスト追加数 |
|---|---|---|---|---|
| 1 | Fernet 暗号化基盤 + tenant_meta_config + RLS + permissions seed | encryption.py, migrations 040/041/042 | 4 | 14 |
| 2 | OAuth start/callback/delete + meta_graph client + Redis state | meta_inbox.py 前半, meta_graph.py | 4 | 53 + 14 |
| 3 | Channels 一覧 API + ChannelsPage Frontend | GET /meta/channels, ChannelsPage.tsx, OAuthCallbackPage.tsx | 3 | 9 |
| 4 | 会話一覧 + メッセージ取得 + Inbox 表示 (左右ペイン) | GET /conversations, GET /leads/{id}/messages, mark-read, InboxPage.tsx | 3 | 28 |
| 5 | メッセージ送信 + 24h ルール + 返信フォーム | messaging_window.py, POST /leads/{id}/messages, lib/messages.ts | 4 | 40 |
| 6 | Instagram 受信 + webhook 改修 + tenant_meta_config 連携 | webhook.py 改修, _persist_meta_message ヘルパー | 2 | 32 |
| 7 | 撮影台本 + ドキュメント整備 + 運用準備 | docs/META_APP_REVIEW_*, docs/PHASE_1D_* | (本 Sprint) | (コード変更ゼロ) |
| **合計** | — | — | **20+** | **190 件** |

各 Sprint は Generator → Evaluator → Reviewer の 3 段パイプラインを通過し、すべて develop ブランチに PR として merge 済（PR #197, #198, #200, #202, #203, #204）。

---

## 4. エンドポイント一覧

### 4-1. OAuth 接続（meta_inbox.py）

| メソッド | パス | 認証 | Permission | 説明 |
|---|---|---|---|---|
| POST | `/api/v1/meta/connect/start` | JWT | `channels.manage` | OAuth 認可 URL + state 発行（state は Redis に Fernet 暗号化で TTL 10 分保存） |
| GET | `/api/v1/meta/connect/callback` | JWT | `channels.manage` | code/state 受領 → Page Access Token 交換 → tenant_meta_config に Fernet 暗号化保存 → Frontend へ redirect |
| DELETE | `/api/v1/meta/connect/{page_id}` | JWT | `channels.manage` | subscribed_apps DELETE + tenant_meta_config.is_active=FALSE |

### 4-2. Channels 一覧（meta_inbox.py）

| メソッド | パス | 認証 | Permission | 説明 |
|---|---|---|---|---|
| GET | `/api/v1/meta/channels` | JWT | `channels.view` | 接続済み Page 一覧（**Page Access Token は返却に含めない**） |

### 4-3. 会話一覧（meta_inbox.py）

| メソッド | パス | 認証 | Permission | 説明 |
|---|---|---|---|---|
| GET | `/api/v1/conversations` | JWT | `messaging.view` | meta_messages を lead_id で集約、最新 1 件 + 未読数 |

クエリ: `?platform=messenger\|instagram\|all`, `?unread_only=true`, `?cursor=<id>`, `?limit=50`

### 4-4. メッセージ取得・送信・既読（leads.py）

| メソッド | パス | 認証 | Permission | 説明 |
|---|---|---|---|---|
| GET | `/api/v1/leads/{lead_id}/messages` | JWT | `messaging.view` | 時系列 + lead 情報 + messaging_window 計算結果 |
| POST | `/api/v1/leads/{lead_id}/messages` | JWT | `messaging.send` | 24h/7d 判定 → Send API → meta_messages INSERT |
| POST | `/api/v1/leads/{lead_id}/messages/mark-read` | JWT | `messaging.view` | direction=inbound, seen_at IS NULL を一括更新 |

### 4-5. Webhook（webhook.py、Sprint 6 改修）

| メソッド | パス | 認証 | 説明 |
|---|---|---|---|
| GET | `/api/v1/webhook/messenger` | Verify Token | Webhook 検証 hub.challenge エコー |
| POST | `/api/v1/webhook/messenger` | HMAC | object='page'/'instagram' 両対応、tenant_meta_config 逆引き |

### 4-6. Data Deletion Callback（meta.py、Phase 5 で稼働）

| メソッド | パス（フル URL） | 認証 | 説明 |
|---|---|---|---|
| POST | `https://api.salesanchor.jp/api/v1/meta/data-deletion` | signed_request (HMAC-SHA256) | B1-B7 で実装済、本 Phase では touch しない |
| GET | `https://api.salesanchor.jp/api/v1/meta/deletion-status?code={confirmation_code}` | なし（公開、CORS で salesanchor.jp 許可） | Status Page バックエンド（confirmation_code 形式: `DEL-YYYYMMDD-xxxx`） |
| GET | `https://salesanchor.jp/deletion-status?code={confirmation_code}` | なし（公開） | Status Page LP（Astro 静的、上記 API を fetch） |

> 注: Callback URL は `api.salesanchor.jp` サブドメイン配下である点に注意（`salesanchor.jp` は LP 静的サイトのみ serve）。詳細は `docs/data_deletion_callback_design.md` D-1 行（Phase 5 / 2026-04-29 確定）を参照。

---

## 5. データモデル一覧

### 5-1. tenant_meta_config (per-tenant schema, migration 040)

| 列 | 型 | 説明 |
|---|---|---|
| `id` | SERIAL PK | — |
| `tenant_id` | INTEGER | RLS フィルタ用 |
| `page_id` | VARCHAR(50) | Facebook Page ID |
| `page_name` | VARCHAR(200) | 表示用 |
| `page_access_token_encrypted` | BYTEA | **Fernet 暗号化済**（生 token は保存しない） |
| `page_token_expires_at` | TIMESTAMPTZ | 約 60 日 |
| `instagram_business_account_id` | VARCHAR(50) | nullable |
| `instagram_username` | VARCHAR(100) | nullable |
| `subscribed_fields` | JSONB | OAuth 時に subscribe した field 一覧 |
| `connected_by_staff_id` | INTEGER | staff(id) FK |
| `connected_at` | TIMESTAMPTZ | — |
| `last_token_refreshed_at` | TIMESTAMPTZ | Phase 1-E でリフレッシュ Cron が更新 |
| `is_active` | BOOLEAN | 切断時 FALSE |
| `deactivated_at` | TIMESTAMPTZ | 切断時刻 |
| `notes` | TEXT | 運用メモ |
| `created_at` / `updated_at` | TIMESTAMPTZ | — |

- **UNIQUE INDEX**: `(tenant_id, page_id) WHERE is_active=TRUE`（複数 Page 許容、ただし同一 page_id を Active 重複させない）
- **RLS Policy**: `tenant_isolation_tenant_meta_config`

### 5-2. meta_messages (per-tenant schema, migration 012 + 041)

migration 012 既存列：
- `id`, `lead_id`, `platform`, `sender_id`, `recipient_id`, `message_text`, `message_id` (uniq), `direction`, `raw_payload`, `created_at`, `tenant_id`, `source` (uniq)

migration 041 追加列（Sprint 4 で適用）:
- `recipient_id` VARCHAR(100) — outbound の宛先 PSID/IGSID
- `messaging_type` VARCHAR(20) — `RESPONSE` / `MESSAGE_TAG` / `UPDATE`
- `message_tag` VARCHAR(50) — `HUMAN_AGENT` 等
- `sent_by_staff_id` INTEGER FK staff(id)
- `error_code` VARCHAR(50) — Meta error code（送信失敗時）
- `error_message` TEXT — PII 除去済エラー文言
- `seen_at` TIMESTAMPTZ — 既読時刻（mark-read API で更新）
- `seen_by_staff_id` INTEGER FK staff(id) — 既読操作者

部分インデックス:
- `idx_meta_messages_lead_unread ON meta_messages(lead_id, created_at) WHERE direction='inbound' AND seen_at IS NULL`
- `idx_meta_messages_lead_created ON meta_messages(lead_id, created_at DESC)`

### 5-3. permissions (public.permissions, migration 042 で +4 件 seed)

| permission_key | 説明 | 付与ロール |
|---|---|---|
| `channels.view` | Channels 一覧の閲覧 | Owner, Admin |
| `channels.manage` | OAuth 接続・切断 | Owner, Admin |
| `messaging.view` | Inbox 閲覧・既読操作 | Owner, Admin |
| `messaging.send` | メッセージ送信 | Owner, Admin |

### 5-4. audit_logs (public, 既存)

OAuth 接続イベント (`meta.connect.start`, `meta.connect.callback`, `meta.connect.disconnect`) と、送信失敗 (`meta.send.failure`) と、Fernet 復号失敗 (`encryption.decrypt.failure`) を記録。

---

## 6. Frontend ルート一覧

| Path | コンポーネント | Sprint | 説明 |
|---|---|---|---|
| `/login` | `LoginPage` | (既存) | Firebase Auth ログイン |
| `/` | `DashboardPage` | (既存) | ダッシュボード |
| `/channels` | `ChannelsPage` | 3 | Meta Page 一覧 + 接続/切断 UI |
| `/channels/oauth/callback` | `OAuthCallbackPage` | 3 | OAuth callback 処理 |
| `/lead-chat` | `InboxPage` | 4 (5 で送信機能追加) | Inbox 2 ペイン UI（旧 ComingSoonPage を差し替え） |
| その他 | (既存ページ群) | — | Customers, Companies, Leads 等は touch せず |

ナビ（`Layout.tsx`）の管理メニューに Sprint 3 で「Channels」リンク追加済。

### 6-1. Frontend ヘルパー

| Path | Sprint | 説明 |
|---|---|---|
| `frontend/src/lib/messages.ts` | 5 | 会話・メッセージ・送信 API のラッパ集約 |

---

## 7. テスト一覧

### 7-1. Backend テスト（pytest）

| ファイル | Sprint | 件数 |
|---|---|---|
| `tests/test_encryption.py` | 1 | 14 |
| `tests/test_rls_tenant_meta_config.py` | 1 | (RLS skip-on-sqlite 対応) |
| `tests/test_meta_graph.py` | 2 | 25 |
| `tests/test_oauth_state_storage.py` | 2 | 14 |
| `tests/test_meta_inbox_oauth.py` | 2 | 14 |
| `tests/test_rls_tenant_meta_config_postgres.py` | 2 | 2 (skip on SQLite) |
| `tests/test_meta_channels.py` | 3 | 9 |
| `tests/test_conversations.py` | 4 | 11 |
| `tests/test_messages.py` | 4 | 17 |
| `tests/test_messaging_window.py` | 5 | 21 |
| `tests/test_message_send.py` | 5 | 19 |
| `tests/test_webhook_instagram.py` | 6 | 32 |
| **Phase 1-D 合計** | — | **190 件** |

最新の develop ブランチで `pytest` を流すと **372 passed / 3 skipped / 0 failed / 0 errors** （Sprint 6 PR #204 マージ後の baseline）。

### 7-2. Frontend テスト

Vitest 未導入のため、Sprint 1-6 では型チェック (`tsc`) + `vite build` でリグレッション確認のみ実施。Vitest 導入は Phase 1-E。

### 7-3. E2E テスト

Playwright 自動化は Phase 1-E。Sprint 7 では撮影台本 (`META_APP_REVIEW_SCREENCAST_SCRIPT.md`) でカバーし、手動撮影リハーサルで担保する方針。

---

## 8. 環境変数（Phase 1-D で追加）

詳細は `docs/ENVIRONMENT_VARIABLES.md` 参照。

| 変数名 | 必須 | 用途 |
|---|---|---|
| `METADATA_FERNET_KEY` | ✅ | Page Access Token + OAuth state の Fernet 暗号化鍵 |
| `META_APP_ID` | ✅ | OAuth client_id |
| `META_APP_SECRET` | ✅ (既存) | HMAC 検証 + OAuth code 交換 |
| `META_OAUTH_REDIRECT_URI` | ✅ | OAuth callback URL |
| `META_GRAPH_API_VERSION` | ✅ | デフォルト v19.0 |
| `META_VERIFY_TOKEN` | ✅ (既存) | Webhook hub.verify_token |
| `META_PAGE_ID` | ⚠ レガシー | 後方互換 fallback、Phase 1-E で削除予定 |
| `ENFORCE_METADATA_FERNET_KEY` | optional | "1" で起動時 fail-fast |
| `FRONTEND_BASE_URL` | optional | OAuth callback 後の redirect 先（既定 `https://app.salesanchor.jp`） |

---

## 9. VPS 適用 Runbook

### 9-1. 適用順序

```bash
# Mac 側で develop に Sprint 7 PR が merge 済を確認
# VPS 側
ssh ubuntu@49.212.137.46
cd /home/ubuntu/jarvis

# 1. .env に新規変数注入（METADATA_FERNET_KEY, META_APP_ID, META_OAUTH_REDIRECT_URI 等）
# Bitwarden から値を取得 → .env を直接編集
nano .env

# 2. develop の最新を pull
git pull origin develop

# 3. migration 適用（040, 041, 042 すべて冪等、既適用ならスキップ）
docker compose exec backend python /app/scripts/apply_migration.py 040
docker compose exec backend python /app/scripts/apply_migration.py 041
docker compose exec backend python /app/scripts/apply_migration.py 042

# 4. backend 再ビルド（cryptography パッケージは既に requirements.txt にあり）
docker compose build backend
docker compose up -d backend

# 5. frontend ビルド（OAuthCallbackPage / ChannelsPage / InboxPage 反映）
docker compose build frontend
docker compose up -d frontend

# 6. 起動確認
docker compose logs backend | grep -i "fernet\|encryption" | tail -5
docker compose ps

# 7. 疎通確認
curl -s https://api.salesanchor.jp/health | jq
curl -s https://api.salesanchor.jp/openapi.json | jq '.paths | keys[] | select(test("meta|conversations"))'
```

### 9-2. ロールバック手順

migration 040, 041, 042 は **すべて additive**（既存テーブル/列の DROP なし）のため、コードのみロールバックすれば足りる：

```bash
# VPS 側
git checkout <previous-tag>
docker compose build backend frontend
docker compose up -d backend frontend
```

データは残るが、既存 router を呼ばなくなるため UI からは見えなくなる。完全削除が必要な場合は `tenant_meta_config` を `DROP TABLE` する down migration を別途用意（本 Phase では未提供）。

### 9-3. 切戻し条件

- backend が起動しない（METADATA_FERNET_KEY 不正で fail-fast 等）
- 既存 `/lead-chat` が壊れて顧客の業務が止まる
- Webhook 受信に regression が出る

---

## 10. 既知の制約・運用 TODO（Phase 1-E follow-up）

詳細は `docs/PHASE_1E_FOLLOW_UP_BACKLOG.md` 参照。サマリー：

### 10-1. High priority

- [ ] Page Access Token の **60 日リフレッシュ Cron**（現状は手動再接続）
- [ ] `force_human_agent_tag` を UI で明示する（自動判定だけでは審査担当が誤解する可能性）
- [ ] PostgreSQL CI（現状 SQLite で CI、PostgreSQL 固有の RLS/JSONB は手動確認）
- [ ] Playwright E2E 自動化

### 10-2. Medium priority

- [ ] 複数 Page 接続時の Inbox フィルタ UI
- [ ] メッセージ送信失敗時の赤枠バブル（現状は alert のみ）
- [ ] customer_name を Graph API 補完（現状 PSID/IGSID のまま）
- [ ] `messages.ts` の cursor pagination

### 10-3. Low priority

- [ ] 添付ファイル送受信
- [ ] meta_page_routing view 化（現状 webhook.py で逐次 SELECT）
- [ ] SQLite 用 auth_events ミドルウェア
- [ ] Vitest 導入
- [ ] Discord 通知タイトルに platform 表記

---

## 11. Meta App Review 提出までの残作業（Sprint 7 + α）

| # | タスク | 担当 | 状態 |
|---|---|---|---|
| 1 | 撮影台本作成 | Generator (Sprint 7) | ✅ Sprint 7 で完成 |
| 2 | 撮影前チェックリスト | Generator (Sprint 7) | ✅ Sprint 7 で完成 |
| 3 | Phase 1-D 全体ドキュメント | Generator (Sprint 7) | ✅ 本ドキュメント |
| 4 | Phase 1-E follow-up リスト | Generator (Sprint 7) | ✅ Sprint 7 で完成 |
| 5 | VPS .env 注入 | しんごさん | ⏳ Sprint 7 直後 |
| 6 | VPS migration 適用 + コンテナ再ビルド | しんごさん | ⏳ Sprint 7 直後 |
| 7 | VPS 動作確認（OAuth → 受信 → 送信 → 切断） | しんごさん | ⏳ Sprint 7 直後 |
| 8 | 24h 経過済会話の準備（撮影前日に inbound DM） | しんごさん | ⏳ 撮影前日 |
| 9 | 撮影リハーサル | しんごさん | ⏳ 撮影日 |
| 10 | 撮影本番 | しんごさん | ⏳ 撮影日 |
| 11 | 編集 + アップロード | しんごさん | ⏳ 撮影後 |
| 12 | Master Checklist v1.1 更新 | しんごさん | ⏳ 撮影後 |
| 13 | Meta App Review Submit | しんごさん | ⏳ 最終 |

---

## 12. 関連ドキュメント

- 仕様書本体: `.claude-pipeline/spec.md`
- 撮影台本: `docs/META_APP_REVIEW_SCREENCAST_SCRIPT.md`
- 撮影前チェックリスト: `docs/META_APP_REVIEW_PRE_RECORDING_CHECKLIST.md`
- Phase 1-E follow-up: `docs/PHASE_1E_FOLLOW_UP_BACKLOG.md`
- 環境変数: `docs/ENVIRONMENT_VARIABLES.md`
- Release Notes: `docs/PHASE_1D_RELEASE_NOTES.md`
- Data Deletion 既存設計: `docs/data_deletion_callback_design.md`
- Discord Gateway 既存設計: `docs/ADR-009_discord_gateway.md`

---

## 13. 連絡先

実装に関する質問は GitHub Issue または Slack `#salesanchor-dev` まで。Meta App Review 提出フローは Master Checklist v1.1 オーナー（しんごさん）まで。
