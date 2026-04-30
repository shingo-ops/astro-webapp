# Phase 1-D Release Notes — Meta Inbox UI

| 項目 | 内容 |
|---|---|
| ステータス | Sprint 1〜6 完了 + Sprint 7（運用ドキュメント整備） |
| リリース予定 | 2026-04-30 〜 2026-05 上旬（VPS 適用 + 撮影リハ） |
| 対象 | Meta App Review 提出に必要な Inbox UI / OAuth / 暗号化基盤 |
| 関連 | `docs/PHASE_1D_META_INBOX_OVERVIEW.md`, `.claude-pipeline/spec.md` |

このリリースノートは Phase 1-D（Sprint 1〜7）でリリースされる変更を **運用者・しんごさん向け** にまとめたもの。

---

## 1. ハイライト

- **Inbox UI が動く**: Messenger と Instagram DM を Sales Anchor の Inbox 1 画面で受信・返信できるようになる
- **OAuth 接続 UI**: しんごさんが UI 上で Facebook Page を接続・切断できる（環境変数直書きから卒業）
- **24h ルール自動判定**: メッセージ送信時、Meta の 24h メッセージング窓を自動判定。24h 以内 = `RESPONSE`、24h-7d = `MESSAGE_TAG (HUMAN_AGENT)`、7d 超 = 送信不可
- **Page Access Token 暗号化**: Fernet で暗号化して DB に保存、API レスポンスにも含めない（PII 保護）
- **Instagram 受信対応**: 既存 Messenger 経路を壊さず Instagram DM 受信を追加

---

## 2. Sprint ごとの変更内容

### Sprint 1: 基盤（暗号化 + tenant_meta_config + RLS + permissions）

PR: [#197](https://github.com/shingo-ops/salesanchor/pull/197)

- 新規ファイル:
  - `backend/app/services/encryption.py` — Fernet wrapper（encrypt / decrypt / rotate）
  - `migrations/040_create_tenant_meta_config.sql` — Page 接続情報テーブル + RLS Policy
  - `migrations/041_extend_meta_messages.sql` — 送信側列追加（recipient_id, messaging_type, message_tag, sent_by_staff_id, error_code, error_message, message_id, seen_at, seen_by_staff_id）
  - `migrations/042_seed_meta_inbox_permissions.sql` — channels.view/manage、messaging.view/send 4 権限を seed + Owner/Admin に付与
- テスト: 14 件
- 環境変数追加: `METADATA_FERNET_KEY`, `ENFORCE_METADATA_FERNET_KEY`

### Sprint 2: OAuth 接続バックエンド

PR: [#198](https://github.com/shingo-ops/salesanchor/pull/198)

- 新規ファイル:
  - `backend/app/services/meta_graph.py` — Meta Graph API httpx クライアント
  - `backend/app/services/oauth_state_storage.py` — Redis state ストレージ（Fernet 暗号化、TTL 10 分）
  - `backend/app/routers/meta_inbox.py` — OAuth start/callback/delete endpoint
- 新エンドポイント:
  - `POST /api/v1/meta/connect/start`
  - `GET /api/v1/meta/connect/callback`
  - `DELETE /api/v1/meta/connect/{page_id}`
- テスト: 67 件（25 + 14 + 14 + 14）+ RLS skip-on-sqlite 2 件
- 環境変数追加: `META_APP_ID`, `META_OAUTH_REDIRECT_URI`, `META_GRAPH_API_VERSION`, `FRONTEND_BASE_URL`

### Sprint 3: Channels 一覧 + Frontend

PR: [#200](https://github.com/shingo-ops/salesanchor/pull/200)

- 新規ファイル:
  - `frontend/src/pages/ChannelsPage.tsx` — 接続 Page 一覧 + 切断 ConfirmModal
  - `frontend/src/pages/OAuthCallbackPage.tsx` — OAuth callback 処理
- 新エンドポイント:
  - `GET /api/v1/meta/channels`
- 新ルート:
  - `/channels` — ChannelsPage
  - `/channels/oauth/callback` — OAuthCallbackPage
- ナビ: 管理メニューに「Channels」リンク追加
- テスト: 9 件（backend）

### Sprint 4: 会話一覧 + Inbox 表示

PR: [#202](https://github.com/shingo-ops/salesanchor/pull/202)

- 新規ファイル:
  - `frontend/src/pages/InboxPage.tsx` — 2 ペイン UI（左: 会話リスト、右: メッセージ表示）
- 新エンドポイント:
  - `GET /api/v1/conversations` — 会話一覧（platform フィルタ、未読フィルタ対応）
  - `GET /api/v1/leads/{lead_id}/messages` — 時系列メッセージ + lead 情報 + messaging_window
  - `POST /api/v1/leads/{lead_id}/messages/mark-read` — 既読マーク
- 既存ルート差し替え: `/lead-chat` を ComingSoonPage → InboxPage
- 機能: 10 秒 polling、`?lead_id=` deep link、平台 (Messenger/Instagram) バッジ、24h バナー
- テスト: 28 件

### Sprint 5: メッセージ送信 + 24h ルール

PR: [#203](https://github.com/shingo-ops/salesanchor/pull/203)

- 新規ファイル:
  - `backend/app/services/messaging_window.py` — 24h/7d 判定 helper
  - `frontend/src/lib/messages.ts` — Frontend API ヘルパー集約
- 新エンドポイント:
  - `POST /api/v1/leads/{lead_id}/messages` — メッセージ送信（Meta Send API 呼出）
- 機能:
  - 24h 内 → `messaging_type=RESPONSE`
  - 24h-7d → `messaging_type=MESSAGE_TAG, message_tag=HUMAN_AGENT`
  - 7d 超 → 400 Error
  - InboxPage の返信フォーム実装、IME composition guard
- 改善:
  - `conversations` の LEFT JOIN leads に tenant_id 整合性条件追加（Sprint 4 F1）
- テスト: 40 件（21 + 19）

### Sprint 6: Instagram 受信 + webhook 改修

PR: [#204](https://github.com/shingo-ops/salesanchor/pull/204)

- 改修ファイル:
  - `backend/app/routers/webhook.py` — Instagram 対応 + tenant_meta_config 連携 + `_persist_meta_message` ヘルパー化
- 機能:
  - `object='instagram'` 分岐対応
  - tenant 特定を `META_PAGE_ID` 環境変数から DB 由来（`tenant_meta_config.page_id` / `instagram_business_account_id` 逆引き）に置換
  - `META_PAGE_ID` は fallback として残置（Phase 1-E で削除予定）
  - Messenger / Instagram 共通の `_persist_meta_message` ヘルパー（whitelist validation 付き）
- テスト: 32 件（test_webhook_instagram.py）
- regression: Messenger 既存経路完全維持

### Sprint 7: ドキュメント整備（本 Sprint）

PR: (作成中)

- 新規ドキュメント:
  - `docs/META_APP_REVIEW_SCREENCAST_SCRIPT.md` — 撮影台本（7 シーン + ナレーション）
  - `docs/META_APP_REVIEW_PRE_RECORDING_CHECKLIST.md` — 撮影前チェックリスト
  - `docs/PHASE_1D_META_INBOX_OVERVIEW.md` — Phase 1-D 全体ドキュメント
  - `docs/PHASE_1E_FOLLOW_UP_BACKLOG.md` — Phase 1-E 持ち越し項目
  - `docs/ENVIRONMENT_VARIABLES.md` — 環境変数リファレンス
  - `docs/PHASE_1D_RELEASE_NOTES.md` — 本ドキュメント
- コード変更: なし

---

## 3. 新エンドポイント一覧（Phase 1-D で追加）

| メソッド | パス | Permission | Sprint |
|---|---|---|---|
| POST | `/api/v1/meta/connect/start` | `channels.manage` | 2 |
| GET | `/api/v1/meta/connect/callback` | `channels.manage` | 2 |
| DELETE | `/api/v1/meta/connect/{page_id}` | `channels.manage` | 2 |
| GET | `/api/v1/meta/channels` | `channels.view` | 3 |
| GET | `/api/v1/conversations` | `messaging.view` | 4 |
| GET | `/api/v1/leads/{lead_id}/messages` | `messaging.view` | 4 |
| POST | `/api/v1/leads/{lead_id}/messages/mark-read` | `messaging.view` | 4 |
| POST | `/api/v1/leads/{lead_id}/messages` | `messaging.send` | 5 |

webhook (`/api/v1/webhook/messenger`) は既存だが Sprint 6 で大幅改修。

---

## 4. 新環境変数（Phase 1-D で追加）

詳細は `docs/ENVIRONMENT_VARIABLES.md` を参照。

| 変数名 | 必須 | Sprint |
|---|---|---|
| `METADATA_FERNET_KEY` | ✅ | 1 |
| `ENFORCE_METADATA_FERNET_KEY` | optional | 1 |
| `META_APP_ID` | ✅ | 2 |
| `META_OAUTH_REDIRECT_URI` | ✅ | 2 |
| `META_GRAPH_API_VERSION` | ✅ | 2 |
| `FRONTEND_BASE_URL` | optional | 2 |

---

## 5. データベース変更（Phase 1-D で追加）

| Migration | 内容 | Sprint |
|---|---|---|
| 040 | per-tenant `tenant_meta_config` テーブル + RLS Policy + 部分 UNIQUE INDEX + IG ID INDEX | 1 |
| 041 | `meta_messages` 列拡張（送信側列 + 既読列、計 9 列） + 部分 INDEX 2 本 | 1 (Sprint 4 で適用確認) |
| 042 | public.permissions に 4 件 seed + role_permissions に Owner/Admin 付与 | 1 |

すべて **additive 変更**（既存列の DROP/RENAME なし）。冪等。

---

## 6. テスト数の推移

| Sprint | 累計 passed | 増分 |
|---|---|---|
| Phase 1-D 開始前 | 197 | (baseline) |
| Sprint 1 完了 | 211 | +14 |
| Sprint 2 完了 | 264 + 2 skip | +53 + 2 |
| Sprint 3 完了 | 273 | +9 |
| Sprint 4 完了 | 301 | +28 |
| Sprint 5 完了 | 341 | +40 |
| Sprint 6 完了 | 372 + 3 skip | +31 |
| Phase 1-D 合計増分 | — | **+175 件**（実機計測 = 372 - 197 = 175） |

最新 develop での pytest 結果: **372 passed / 3 skipped / 0 failed / 0 errors**。

---

## 7. VPS 適用手順（しんごさん作業）

詳細は `docs/PHASE_1D_META_INBOX_OVERVIEW.md` §9 参照。

```bash
# Mac 側
gh pr merge <Sprint 7 PR>  # develop に merge

# VPS 側
ssh ubuntu@49.212.137.46
cd /home/ubuntu/jarvis

# 1. .env に新規変数を追加
nano .env
# → METADATA_FERNET_KEY, META_APP_ID, META_OAUTH_REDIRECT_URI, ENFORCE_METADATA_FERNET_KEY=1 等

# 2. develop 最新を pull
git pull origin develop

# 3. migration 適用（040 / 041 / 042、すべて冪等）
docker compose exec backend python /app/scripts/apply_migration.py 040
docker compose exec backend python /app/scripts/apply_migration.py 041
docker compose exec backend python /app/scripts/apply_migration.py 042

# 4. backend / frontend 再ビルド
docker compose build backend frontend
docker compose up -d backend frontend

# 5. 起動確認
docker compose logs backend | grep -i "fernet" | tail -5
curl -s https://api.salesanchor.jp/health | jq

# 6. 動作確認（手動）
# - https://app.salesanchor.jp/channels で OAuth 通し
# - https://app.salesanchor.jp/lead-chat で Inbox 表示
```

---

## 8. ロールバック / 切戻し条件

詳細は `docs/PHASE_1D_META_INBOX_OVERVIEW.md` §9-2 参照。

migration はすべて additive のため、コードのみロールバックで足りる：

```bash
# VPS 側
git checkout <previous-tag>
docker compose build backend frontend
docker compose up -d backend frontend
```

データは残るが既存 router を呼ばなくなる。完全削除が必要な場合は `tenant_meta_config` を `DROP TABLE` する down migration を別途用意（本 Phase では未提供）。

切戻し条件:
- backend が起動しない（METADATA_FERNET_KEY 不正で fail-fast 等）
- 既存 `/lead-chat` が壊れて顧客の業務が止まる
- Webhook 受信に regression が出る

---

## 9. 既知の制約・運用 TODO

詳細は `docs/PHASE_1E_FOLLOW_UP_BACKLOG.md` を参照。代表的な項目：

### High priority

- Page Access Token の **60 日リフレッシュ Cron**（Phase 1-E 着手時に最優先）
- Playwright E2E 自動化
- PostgreSQL CI 構築

### Medium priority

- 複数 Page 接続時の Inbox フィルタ UI
- 送信失敗バブルの赤枠表示
- customer_name の Graph API 補完

### Low priority

- 添付ファイル対応
- meta_page_routing view 化（webhook 性能改善）
- Vitest 導入

---

## 10. Meta App Review 提出までの残タスク

詳細は `docs/PHASE_1D_META_INBOX_OVERVIEW.md` §11 参照。

| # | タスク | 担当 | 状態 |
|---|---|---|---|
| 1〜4 | ドキュメント整備 | Sprint 7 | ✅ 完了予定 |
| 5〜7 | VPS 適用 + 動作確認 | しんごさん | ⏳ |
| 8 | 24h 経過済会話の準備 | しんごさん | ⏳ |
| 9〜11 | 撮影リハ + 本番 + 編集 | しんごさん | ⏳ |
| 12〜13 | Master Checklist 更新 + 提出 | しんごさん | ⏳ |

---

## 11. 関連ドキュメント

- 仕様書: `.claude-pipeline/spec.md`
- 全体ドキュメント: `docs/PHASE_1D_META_INBOX_OVERVIEW.md`
- 撮影台本: `docs/META_APP_REVIEW_SCREENCAST_SCRIPT.md`
- 撮影前チェックリスト: `docs/META_APP_REVIEW_PRE_RECORDING_CHECKLIST.md`
- Phase 1-E backlog: `docs/PHASE_1E_FOLLOW_UP_BACKLOG.md`
- 環境変数: `docs/ENVIRONMENT_VARIABLES.md`

---

## 12. クレジット

- 設計: Planner agent (Claude Code, 2026-04-30)
- 実装: Generator agent (Sprint 1〜6)
- 評価: Evaluator agent + Reviewer agent
- 監督・本番反映: しんごさん

Phase 1-D 8 営業日想定で着手 → 実機 7 Sprint で完了予定。
