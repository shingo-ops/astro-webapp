# Data Deletion Callback 設計書（B1-B7 実装計画）

| 項目 | 内容 |
|---|---|
| ステータス | **Implementation in Progress** |
| 起草日 | 2026-04-29 |
| 元仕様 | `data_deletion_instructions.docx v1.0` (2026-04-23, しんごさん作成、Google Drive 保管) |
| 対象 | Meta App Review チェックリスト v1.1 §B (B1〜B7) |
| 担当 | Hikky-dev |
| 参考実装 | `backend/app/routers/webhook.py`（Meta Webhook の HMAC 検証参考）|

## 0. 元仕様からの主要な決定事項

| # | 項目 | 仕様書 v1.0 | 本実装での扱い |
|---|---|---|---|
| **D-1** | Callback URL ドメイン | `https://salesanchor.jp/api/v1/meta/data-deletion` | **`https://api.salesanchor.jp/api/v1/meta/data-deletion` に変更** ⚠️ |
| **D-2** | Status ページ URL | `https://salesanchor.jp/deletion-status?code=...` | 仕様書通り（LP 側、Astro 静的ページ） |
| **D-3** | 検証アルゴリズム | HMAC-SHA256 (App Secret) | 仕様書通り（既存 `webhook.py` と同じ） |
| **D-4** | レスポンス形式 | unquoted JSON（template literal で手動生成） | 仕様書通り |
| **D-5** | 削除対象テーブル | `lead_channels`, `meta_messages`, `raw_webhook_events` | `meta_messages` のみ実在、他は今後 |
| **D-6** | 監査ログテーブル | `data_deletion_logs` | migration 039 で新設 |
| **D-7** | メール送信 | さくらメール経由 SMTP | 環境変数で設定、未設定時は idle |
| **D-8** | 削除実行タイミング | Meta callback は 3 秒以内応答、削除は async | Celery タスクで非同期実行 |

**D-1 の理由**: Phase 5 で `api.salesanchor.jp` (API only) サブドメインが本番稼働開始（2026-04-29）。docx は 2026-04-23 起草で、当時はまだサブドメイン構成が未確定。`salesanchor.jp` は LP 静的サイトのみを serve し `/api/` プロキシは無いため、Meta callback URL は `api.salesanchor.jp` 配下が論理的に正しい。docx v1.1 への更新もしんごさんに依頼予定。

## 1. アーキテクチャ概観

```
Meta Platform                     api.salesanchor.jp                salesanchor.jp
    |                                    |                                 |
    | 1. POST signed_request             |                                 |
    +----------------------------------->|                                 |
    |                                    |                                 |
    |                                    | 2. HMAC verify                  |
    |                                    | 3. Generate codes               |
    |                                    | 4. Insert data_deletion_logs    |
    |                                    | 5. Enqueue Celery task          |
    |                                    | 6. Return unquoted JSON         |
    |   { url: "...", confirmation_code: "..." }                           |
    |<-----------------------------------+                                 |
    |                                    |                                 |
    |                                    | (async) Celery worker:          |
    |                                    |  - Search per-tenant meta_messages by sender_id
    |                                    |  - Delete matching rows
    |                                    |  - Update log status=completed   |
    |                                    |  - Send completion email         |
    |                                    |                                 |
    |                                    |                                 |
    |                                                                      |
    User                                                                   |
    |  Visit https://salesanchor.jp/deletion-status?code=DEL-...           |
    +--------------------------------------------------------------------->|
    |                                                                      |
    |                                    | 7. Astro page loads (static)    |
    |                                    | 8. JS reads ?code=...           |
    |                                    | 9. fetch api.salesanchor.jp     |
    |                                    |    /api/v1/meta/deletion-status |
    |                                    |    ?code=DEL-...                |
    |                                    |                                 |
    |                                    | 10. Returns { status, completed_at, ... } |
    |   Display status                   |<--------------------------------+
    |<---------------------------------------------------------------------|
```

## 2. 提供物（実装ファイル）

### 2-1. DB Migration (B3)

**ファイル**: `migrations/039_create_data_deletion_logs.sql`

仕様書 §5.1 のスキーマをそのまま実装。`public` schema 配下（テナント横断のため）、idempotent (`CREATE TABLE IF NOT EXISTS`)。

```sql
CREATE TABLE IF NOT EXISTS public.data_deletion_logs (
    id BIGSERIAL PRIMARY KEY,
    request_id VARCHAR(50) NOT NULL UNIQUE,        -- REQ-YYYYMMDD-xxx
    confirmation_code VARCHAR(50) NOT NULL UNIQUE, -- DEL-YYYYMMDD-xxxx
    channel VARCHAR(20) NOT NULL CHECK (channel IN ('meta_callback', 'email')),
    user_type VARCHAR(20) NOT NULL CHECK (user_type IN ('user', 'end_user')),
    identifier_type VARCHAR(50),
    identifier_value VARCHAR(200),
    tenant_id INTEGER,
    requested_at TIMESTAMPTZ NOT NULL,
    started_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    status VARCHAR(20) NOT NULL DEFAULT 'received'
        CHECK (status IN ('received','verifying','processing','completed','failed','rejected')),
    data_items_deleted JSONB,
    error_message TEXT,
    handled_by VARCHAR(100),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_deletion_logs_request_id ON public.data_deletion_logs (request_id);
CREATE INDEX IF NOT EXISTS idx_deletion_logs_confirmation_code ON public.data_deletion_logs (confirmation_code);
CREATE INDEX IF NOT EXISTS idx_deletion_logs_status ON public.data_deletion_logs (status);
```

### 2-2. Backend Router (B1, B2, B4)

**ファイル**: `backend/app/routers/meta.py` (新規)

| Endpoint | Method | Auth | 用途 |
|---|---|---|---|
| `/api/v1/meta/data-deletion` | POST | 不要（Meta から POST）| Data Deletion Callback |
| `/api/v1/meta/deletion-status` | GET | 不要（公開ステータス確認）| ステータス API（B5 連携）|

**B1-B4 の実装シーケンス**:

1. `POST /api/v1/meta/data-deletion` を受ける
2. `signed_request=...` フィールドをパース
3. **HMAC-SHA256 検証**（App Secret = `META_APP_SECRET`、`webhook.py` と同じ）
4. payload から `user_id` を取得
5. `request_id` (`REQ-YYYYMMDD-xxx`) と `confirmation_code` (`DEL-YYYYMMDD-xxxx`) を生成
6. `data_deletion_logs` に INSERT (status='received')
7. **Celery task `process_data_deletion(request_id)`** を enqueue
8. **unquoted JSON レスポンス**を template literal で生成して返却（Meta 仕様）

**Celery task `process_data_deletion(request_id)` の挙動**:

1. logs の status='processing' に更新、started_at=NOW()
2. 全 tenant スキーマを `pg_namespace` で列挙
3. 各テナント:
   - `SELECT id FROM {schema}.meta_messages WHERE sender_id = $user_id` で検索
   - HIT した行を DELETE
   - 削除件数を data_items_deleted JSONB に集計
4. status='completed' / completed_at=NOW() に更新
5. メール送信（環境変数あれば）

### 2-3. Status API (B5 backend)

**ファイル**: `backend/app/routers/meta.py` (同上)

```python
@router.get("/api/v1/meta/deletion-status")
async def get_deletion_status(code: str = Query(..., regex=r"^DEL-\d{8}-[a-zA-Z0-9]+$")):
    """確認コードから削除ステータスを返す（公開エンドポイント）。"""
    # data_deletion_logs から SELECT
    # 機密情報は返さない: status, requested_at, completed_at のみ
```

**CORS**: `https://salesanchor.jp` を `ALLOWED_ORIGINS` に追加（LP からの fetch 用）。

### 2-4. Status Page (B5 frontend)

**ファイル**: `lp/src/pages/deletion-status.astro` (新規)

- 静的 Astro ページ（SSG）
- ロード時に JS で `?code=...` をパース
- `fetch('https://api.salesanchor.jp/api/v1/meta/deletion-status?code=...')`
- 結果に応じて表示:
  - 200: 受付内容 + 進捗（received/processing/completed）+ 完了日時
  - 404: 「コードが見つかりません」
  - その他: エラーメッセージ
- バイリンガル（日英並記、他のページと同じ規格）

### 2-5. Email Sender (B6)

**ファイル**: `backend/app/services/email_sender.py` (新規)

- `aiosmtplib` で SMTP 送信（さくらメール想定）
- 環境変数:
  - `SMTP_HOST` (例: `smtp.salesanchor.jp` または `mail.sakura.ad.jp` 系)
  - `SMTP_PORT` (例: 587)
  - `SMTP_USER`
  - `SMTP_PASSWORD`
  - `MAIL_FROM` (例: `support@salesanchor.jp`)
- 未設定なら **idle**（送信せず log のみ）→ Meta App Review テスト時はメール送信は必須ではないため許容
- Celery task から呼ばれる
- テンプレ: 仕様書 §3.3 (受領確認) と §3.4 (完了通知) を文字列定数として埋め込み

### 2-6. nginx Config Update

**ファイル**: `nginx/nginx.conf`

`api.salesanchor.jp` の HTTPS server block には既に `/api/` プロキシがある（PR #184）→ **追加変更不要**。

`salesanchor.jp` の LP 配信 server block にも `/api/` proxy を追加するかは保留（D-1 で D-1 通り api.salesanchor.jp に統一する方針なら不要）。

### 2-7. backend/app/main.py Update

`from app.routers import meta` を追加し、`app.include_router(meta.router, prefix="/api/v1", tags=["meta"])` を追加。`webhook.py` と同じ「認証不要」セクションに配置。

### 2-8. backend/app/tasks.py または celery 構成

既存 Celery task を確認し、`process_data_deletion(request_id)` task を追加。

## 3. SLA と非同期動作

| ステップ | タイミング | 仕様書 §7.1 |
|---|---|---|
| Meta callback 応答 | 3 秒以内 | ✅ status='received' で INSERT してすぐ unquoted JSON を返す |
| 受領確認メール | 24h 以内 | Celery task で送信（即座に enqueue）|
| 削除処理開始 | 7 営業日以内 | Celery task で即時処理 |
| メイン DB 削除完了 | 14 日以内 | Celery task の同実行で完了 |
| バックアップ削除 | 30 日以内 | バックアップ運用は別タスク（範囲外）|
| 完了通知メール | 30 日以内 | Celery task の同実行で送信 |

## 4. テスト計画

### 4-1. ユニットテスト

- `test_meta_data_deletion.py`:
  - HMAC 不正リクエスト → 403
  - HMAC 正規リクエスト → 200 + unquoted JSON 形式
  - signed_request 不正フォーマット → 400
  - 二重リクエスト（同じ user_id）→ idempotent な挙動
- `test_deletion_status.py`:
  - 存在するコード → 200 + status
  - 存在しないコード → 404
  - 不正なフォーマット → 400 (Pydantic regex)

### 4-2. Meta 公式テストツール（B7、本番）

- Meta Developer Dashboard で Data Deletion Callback URL を `https://api.salesanchor.jp/api/v1/meta/data-deletion` に登録
- "Test Data Deletion Callback" ボタンを押下
- 期待動作:
  - HTTP 200
  - レスポンスに `url` と `confirmation_code` が含まれる
  - 3 秒以内に応答
- 応答ボディの形式が **unquoted JSON** であることを Meta 側で自動検証 → これに不合格だと App Review reject

## 5. 実装ステップ

| # | ステップ | 工数 |
|---|---|---|
| Step 1 | Design doc + migration 039 | 0.5h |
| Step 2 | meta.py router + HMAC + unquoted JSON 応答 (B1, B2, B4) | 1.5h |
| Step 3 | Celery task `process_data_deletion` + per-tenant 削除 | 1.5h |
| Step 4 | deletion-status endpoint + LP page (B5) | 1h |
| Step 5 | email_sender.py + テンプレ (B6) | 1h |
| Step 6 | ユニットテスト追加 | 1h |
| Step 7 | deploy.yml の migrations セクションに 039 を追加 | 0.2h |
| Step 8 | 本番デプロイ + Meta テストツール検証 (B7) | 0.5h（しんごさん作業含む）|
| **合計** | | **~7.2h** |

## 6. ロールバック

- Migration 039 の rollback: `DROP TABLE public.data_deletion_logs;`（明示的に必要なら別 PR で）
- Endpoint の rollback: PR revert で元に戻る
- Meta Dashboard の Callback URL: しんごさんが Meta Developer Dashboard で削除

## 7. 残課題（実装後の TODO）

- [ ] `lead_channels` テーブル（Meta integration Phase 3）が実装されたら、削除処理で参照する
- [ ] `raw_webhook_events` の anonymize（仕様書 §4.2）も Phase 3 で対応
- [ ] バックアップ DB の自動削除フロー（30 日以内、§7.1）— 運用設計が必要
- [ ] data_deletion_instructions.docx を v1.1 に更新（D-1 の URL を `api.salesanchor.jp` に修正）
- [ ] Cron Job for status='received' の長期滞留検出 + アラート

## 8. 関連ドキュメント

- 元仕様: `data_deletion_instructions.docx v1.0` (Google Drive)
- LP 公開ページ: `lp/src/pages/data-deletion.astro`
- Privacy Policy: `lp/src/pages/privacy.astro` (§9 で削除手順を明記)
- Meta App Review チェックリスト v1.1 (Google Doc)
- Phase 5 ドメイン: `docs/PHASE5_DOMAIN_CUTOVER_RUNBOOK.md`
