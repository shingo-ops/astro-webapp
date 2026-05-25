"""
アプリ内カレンダーサービス（calendar_service + google_webhook）単体テスト。

DB・Google API は全てモックする。SQLAlchemy AsyncSession を AsyncMock で代替。

カバー範囲:
  calendar_service:
    - _build_sync_origin_id（純粋関数）
    - _to_google_event_body（純粋関数）
    - _get_sync_mode（DB モック）
    - _is_app_origin（DB モック）
    - list_events（DB モック）
    - create_event（DB モック + Google スキップ）
    - update_event（DB モック）
    - delete_event（DB モック）
    - upsert_from_google（DB モック）

  google_webhook:
    - _get_webhook_address（環境変数）
    - get_tenant_by_channel（DB モック）
    - handle_webhook_notification（sync 通知の無視 / 不明 channel）
    - register_webhook（Google 未接続のスキップ）
    - stop_webhook（レコードなしの早期 return）
    - renew_expiring_webhooks（更新ゼロケース）
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from cryptography.fernet import Fernet

# テスト用環境変数を事前に設定
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
os.environ.setdefault("METADATA_FERNET_KEY", Fernet.generate_key().decode())
os.environ.setdefault("GOOGLE_CALENDAR_CLIENT_ID", "test-client-id")
os.environ.setdefault("GOOGLE_CALENDAR_CLIENT_SECRET", "test-secret")
os.environ.setdefault("GOOGLE_CALENDAR_REDIRECT_URI", "https://api.example.com/callback")


# ---------------------------------------------------------------------------
# ヘルパー: AsyncSession モック
# ---------------------------------------------------------------------------

def _make_db(first_return=None, fetchall_return=None, scalar_return=None):
    """AsyncSession のモックを生成する。"""
    db = AsyncMock()
    db.commit = AsyncMock()

    result = MagicMock()
    result.first = MagicMock(return_value=first_return)
    result.fetchall = MagicMock(return_value=fetchall_return or [])
    result.scalar_one = MagicMock(return_value=scalar_return or 1)
    db.execute = AsyncMock(return_value=result)
    return db


# ===========================================================================
# calendar_service テスト
# ===========================================================================


class TestBuildSyncOriginId:
    def test_format(self):
        from app.services.calendar_service import _build_sync_origin_id
        result = _build_sync_origin_id(tenant_id=1, calendar_event_id=42)
        assert result == "app:1:42"

    def test_different_values(self):
        from app.services.calendar_service import _build_sync_origin_id
        assert _build_sync_origin_id(99, 999) == "app:99:999"


class TestToGoogleEventBody:
    def test_datetime_event(self):
        from app.services.calendar_service import _to_google_event_body
        payload = {
            "title": "ミーティング",
            "start_datetime": "2026-06-01T10:00:00+09:00",
            "end_datetime": "2026-06-01T11:00:00+09:00",
            "is_all_day": False,
        }
        body = _to_google_event_body(payload)
        assert body["summary"] == "ミーティング"
        assert body["start"]["dateTime"] == "2026-06-01T10:00:00+09:00"
        assert body["start"]["timeZone"] == "Asia/Tokyo"
        assert body["end"]["dateTime"] == "2026-06-01T11:00:00+09:00"
        assert "date" not in body["start"]

    def test_all_day_event(self):
        from app.services.calendar_service import _to_google_event_body
        payload = {
            "title": "終日イベント",
            "start_datetime": "2026-06-01",
            "end_datetime": "2026-06-02",
            "is_all_day": True,
        }
        body = _to_google_event_body(payload)
        assert body["start"]["date"] == "2026-06-01"
        assert body["end"]["date"] == "2026-06-02"
        assert "dateTime" not in body["start"]

    def test_with_description_and_location(self):
        from app.services.calendar_service import _to_google_event_body
        payload = {
            "title": "テスト",
            "start_datetime": "2026-06-01T10:00:00+09:00",
            "end_datetime": "2026-06-01T11:00:00+09:00",
            "is_all_day": False,
            "description": "詳細説明",
            "location": "東京都渋谷区",
        }
        body = _to_google_event_body(payload)
        assert body["description"] == "詳細説明"
        assert body["location"] == "東京都渋谷区"

    def test_without_description_and_location(self):
        from app.services.calendar_service import _to_google_event_body
        payload = {
            "title": "テスト",
            "start_datetime": "2026-06-01T10:00:00+09:00",
            "end_datetime": "2026-06-01T11:00:00+09:00",
        }
        body = _to_google_event_body(payload)
        assert "description" not in body
        assert "location" not in body

    def test_empty_title_defaults(self):
        from app.services.calendar_service import _to_google_event_body
        payload = {
            "start_datetime": "2026-06-01T10:00:00+09:00",
            "end_datetime": "2026-06-01T11:00:00+09:00",
        }
        body = _to_google_event_body(payload)
        assert body["summary"] == ""


class TestGetSyncMode:
    @pytest.mark.asyncio
    async def test_returns_sync_mode(self):
        from app.services.calendar_service import _get_sync_mode
        db = _make_db(first_return=("bidirectional",))
        result = await _get_sync_mode(db, tenant_id=1)
        assert result == "bidirectional"

    @pytest.mark.asyncio
    async def test_returns_none_when_no_config(self):
        from app.services.calendar_service import _get_sync_mode
        db = _make_db(first_return=None)
        result = await _get_sync_mode(db, tenant_id=99)
        assert result == "none"


class TestIsAppOrigin:
    @pytest.mark.asyncio
    async def test_returns_true_when_found(self):
        from app.services.calendar_service import _is_app_origin
        db = _make_db(first_return=(1,))
        result = await _is_app_origin(db, google_event_id="google_abc", tenant_id=1)
        assert result is True

    @pytest.mark.asyncio
    async def test_returns_false_when_not_found(self):
        from app.services.calendar_service import _is_app_origin
        db = _make_db(first_return=None)
        result = await _is_app_origin(db, google_event_id="google_xyz", tenant_id=1)
        assert result is False


class TestListEvents:
    @pytest.mark.asyncio
    async def test_returns_empty_list(self):
        from app.services.calendar_service import list_events
        db = _make_db(fetchall_return=[])
        result = await list_events(db, tenant_id=1, start="2026-06-01", end="2026-06-30")
        assert result == []

    @pytest.mark.asyncio
    async def test_returns_events(self):
        from app.services.calendar_service import list_events
        now = datetime(2026, 6, 1, 10, 0, 0, tzinfo=timezone.utc)
        row = (1, 2, "shared", "テスト会議", None, None, now, now, False, None, "app", "synced", 2, now, now)
        db = _make_db(fetchall_return=[row])
        result = await list_events(db, tenant_id=1, start="2026-06-01", end="2026-06-30")
        assert len(result) == 1
        assert result[0]["title"] == "テスト会議"
        assert result[0]["calendar_type"] == "shared"

    @pytest.mark.asyncio
    async def test_shared_type_filter(self):
        """calendar_type=shared でクエリが通ること。"""
        from app.services.calendar_service import list_events
        db = _make_db(fetchall_return=[])
        await list_events(db, tenant_id=1, start="2026-06-01", end="2026-06-30", calendar_type="shared")
        db.execute.assert_called_once()

    @pytest.mark.asyncio
    async def test_personal_type_filter(self):
        """calendar_type=personal + user_id でクエリが通ること。"""
        from app.services.calendar_service import list_events
        db = _make_db(fetchall_return=[])
        await list_events(db, tenant_id=1, start="2026-06-01", end="2026-06-30",
                          calendar_type="personal", user_id=5)
        db.execute.assert_called_once()


class TestCreateEvent:
    @pytest.mark.asyncio
    async def test_create_without_google_sync(self):
        """sync_mode='none' の場合、Google API は呼ばれない。"""
        from app.services.calendar_service import create_event

        # DB: INSERT RETURNING 1, then _get_sync_mode returns 'none'
        db = AsyncMock()
        db.commit = AsyncMock()

        insert_result = MagicMock()
        insert_result.scalar_one = MagicMock(return_value=1)
        sync_result = MagicMock()
        sync_result.first = MagicMock(return_value=("none",))

        db.execute = AsyncMock(side_effect=[insert_result, sync_result])

        payload = {
            "title": "新しいイベント",
            "start_datetime": "2026-06-01T10:00:00+09:00",
            "end_datetime": "2026-06-01T11:00:00+09:00",
            "calendar_type": "shared",
        }
        result = await create_event(db, tenant_id=1, user_id=2, payload=payload)
        assert result["id"] == 1

    @pytest.mark.asyncio
    async def test_create_personal_event(self):
        """personal イベントは user_id がセットされる。"""
        from app.services.calendar_service import create_event

        db = AsyncMock()
        db.commit = AsyncMock()

        insert_result = MagicMock()
        insert_result.scalar_one = MagicMock(return_value=5)
        sync_result = MagicMock()
        sync_result.first = MagicMock(return_value=("none",))
        db.execute = AsyncMock(side_effect=[insert_result, sync_result])

        payload = {
            "title": "個人予定",
            "start_datetime": "2026-06-01T10:00:00+09:00",
            "end_datetime": "2026-06-01T11:00:00+09:00",
            "calendar_type": "personal",
        }
        result = await create_event(db, tenant_id=1, user_id=3, payload=payload)
        assert result["id"] == 5

    @pytest.mark.asyncio
    async def test_create_with_google_sync_failure(self):
        """Google 同期失敗時でも DB に保存される（sync_status='failed'）。"""
        from app.services.calendar_service import create_event

        db = AsyncMock()
        db.commit = AsyncMock()

        insert_result = MagicMock()
        insert_result.scalar_one = MagicMock(return_value=10)
        sync_result = MagicMock()
        sync_result.first = MagicMock(return_value=("bidirectional",))
        update_result = MagicMock()

        db.execute = AsyncMock(side_effect=[insert_result, sync_result, update_result])

        with patch("app.services.google_calendar.create_event", AsyncMock(side_effect=RuntimeError("API error"))):
            payload = {
                "title": "同期失敗テスト",
                "start_datetime": "2026-06-01T10:00:00+09:00",
                "end_datetime": "2026-06-01T11:00:00+09:00",
                "calendar_type": "shared",
            }
            result = await create_event(db, tenant_id=1, user_id=1, payload=payload)
            assert result["id"] == 10


class TestUpdateEvent:
    @pytest.mark.asyncio
    async def test_update_no_fields(self):
        """更新フィールドがない場合は早期 return。"""
        from app.services.calendar_service import update_event
        db = _make_db()
        result = await update_event(db, tenant_id=1, event_id=1, user_id=1, payload={})
        assert result["id"] == 1
        db.execute.assert_not_called()

    @pytest.mark.asyncio
    async def test_update_title_without_google_sync(self):
        """sync_mode='none' / google_event_id なし → Google 同期なし。"""
        from app.services.calendar_service import update_event

        db = AsyncMock()
        db.commit = AsyncMock()
        update_result = MagicMock()
        geid_result = MagicMock()
        geid_result.first = MagicMock(return_value=(None,))  # google_event_id = None
        sync_result = MagicMock()
        sync_result.first = MagicMock(return_value=("none",))

        db.execute = AsyncMock(side_effect=[update_result, geid_result, sync_result])

        result = await update_event(db, tenant_id=1, event_id=3, user_id=1,
                                    payload={"title": "更新タイトル"})
        assert result["id"] == 3


class TestDeleteEvent:
    @pytest.mark.asyncio
    async def test_delete_without_google(self):
        """google_event_id がない場合は Google API を呼ばない。"""
        from app.services.calendar_service import delete_event

        db = AsyncMock()
        db.commit = AsyncMock()
        geid_result = MagicMock()
        geid_result.first = MagicMock(return_value=(None,))
        delete_result = MagicMock()
        sync_result = MagicMock()
        sync_result.first = MagicMock(return_value=("none",))

        db.execute = AsyncMock(side_effect=[geid_result, delete_result, sync_result])
        await delete_event(db, tenant_id=1, event_id=5)
        # commit が呼ばれたことを確認
        db.commit.assert_called()


class TestUpsertFromGoogle:
    @pytest.mark.asyncio
    async def test_skips_when_no_event_id(self):
        from app.services.calendar_service import upsert_from_google
        db = _make_db()
        await upsert_from_google(db, tenant_id=1, google_event={})
        db.execute.assert_not_called()

    @pytest.mark.asyncio
    async def test_deletes_cancelled_event(self):
        from app.services.calendar_service import upsert_from_google

        db = AsyncMock()
        db.commit = AsyncMock()
        origin_result = MagicMock()
        origin_result.first = MagicMock(return_value=None)  # not app origin
        delete_result = MagicMock()
        db.execute = AsyncMock(side_effect=[origin_result, delete_result])

        await upsert_from_google(db, tenant_id=1, google_event={"id": "ev1", "status": "cancelled"})
        db.commit.assert_called()

    @pytest.mark.asyncio
    async def test_skips_app_origin(self):
        from app.services.calendar_service import upsert_from_google

        db = AsyncMock()
        db.commit = AsyncMock()
        origin_result = MagicMock()
        origin_result.first = MagicMock(return_value=(1,))  # app origin found
        db.execute = AsyncMock(return_value=origin_result)

        await upsert_from_google(db, tenant_id=1,
                                 google_event={"id": "ev_app", "status": "confirmed"})
        # execute は _is_app_origin の1回のみ（upsert は呼ばれない）
        assert db.execute.call_count == 1
        db.commit.assert_not_called()

    @pytest.mark.asyncio
    async def test_upserts_valid_event(self):
        from app.services.calendar_service import upsert_from_google

        db = AsyncMock()
        db.commit = AsyncMock()
        origin_result = MagicMock()
        origin_result.first = MagicMock(return_value=None)  # not app origin
        upsert_result = MagicMock()
        db.execute = AsyncMock(side_effect=[origin_result, upsert_result])

        google_event = {
            "id": "ev_google_001",
            "summary": "Google会議",
            "start": {"dateTime": "2026-06-01T10:00:00+09:00"},
            "end": {"dateTime": "2026-06-01T11:00:00+09:00"},
        }
        await upsert_from_google(db, tenant_id=1, google_event=google_event)
        db.commit.assert_called()

    @pytest.mark.asyncio
    async def test_skips_invalid_start_end(self):
        from app.services.calendar_service import upsert_from_google

        db = AsyncMock()
        db.commit = AsyncMock()
        origin_result = MagicMock()
        origin_result.first = MagicMock(return_value=None)
        db.execute = AsyncMock(return_value=origin_result)

        google_event = {
            "id": "ev_no_dates",
            "summary": "日時なし",
            "start": {},
            "end": {},
        }
        await upsert_from_google(db, tenant_id=1, google_event=google_event)
        # start/end なしなので upsert 実行されない
        assert db.execute.call_count == 1
        db.commit.assert_not_called()

    @pytest.mark.asyncio
    async def test_upserts_all_day_event(self):
        from app.services.calendar_service import upsert_from_google

        db = AsyncMock()
        db.commit = AsyncMock()
        origin_result = MagicMock()
        origin_result.first = MagicMock(return_value=None)
        upsert_result = MagicMock()
        db.execute = AsyncMock(side_effect=[origin_result, upsert_result])

        google_event = {
            "id": "ev_all_day",
            "summary": "終日イベント",
            "start": {"date": "2026-06-01"},
            "end": {"date": "2026-06-02"},
        }
        await upsert_from_google(db, tenant_id=1, google_event=google_event)
        db.commit.assert_called()


# ===========================================================================
# google_webhook テスト
# ===========================================================================


class TestGetWebhookAddress:
    def test_default_base_url(self):
        from app.services.google_webhook import _get_webhook_address
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("API_BASE_URL", None)
            addr = _get_webhook_address()
            assert addr == "https://api.salesanchor.jp/api/v1/google-calendar/webhook"

    def test_custom_base_url(self):
        from app.services.google_webhook import _get_webhook_address
        with patch.dict(os.environ, {"API_BASE_URL": "https://test.example.com"}):
            addr = _get_webhook_address()
            assert addr == "https://test.example.com/api/v1/google-calendar/webhook"

    def test_trailing_slash_stripped(self):
        from app.services.google_webhook import _get_webhook_address
        with patch.dict(os.environ, {"API_BASE_URL": "https://test.example.com/"}):
            addr = _get_webhook_address()
            assert not addr.startswith("https://test.example.com//")


class TestGetTenantByChannel:
    @pytest.mark.asyncio
    async def test_returns_none_when_not_found(self):
        from app.services.google_webhook import get_tenant_by_channel
        db = _make_db(first_return=None)
        result = await get_tenant_by_channel(db, channel_id="nonexistent")
        assert result is None

    @pytest.mark.asyncio
    async def test_returns_tenant_info(self):
        from app.services.google_webhook import get_tenant_by_channel
        db = _make_db(first_return=(7,))
        result = await get_tenant_by_channel(db, channel_id="ch_123")
        assert result is not None
        tenant_id, schema_name = result
        assert tenant_id == 7
        assert schema_name == "tenant_007"


class TestHandleWebhookNotification:
    @pytest.mark.asyncio
    async def test_ignores_sync_state(self):
        """resource_state='sync' は何もしない。"""
        from app.services.google_webhook import handle_webhook_notification
        db = _make_db()
        await handle_webhook_notification(db, channel_id="ch_1", resource_state="sync")
        db.execute.assert_not_called()

    @pytest.mark.asyncio
    async def test_returns_early_when_channel_not_found(self):
        """不明な channel_id は早期 return。"""
        from app.services.google_webhook import handle_webhook_notification
        db = _make_db(first_return=None)
        await handle_webhook_notification(db, channel_id="unknown_ch", resource_state="exists")
        # get_tenant_by_channel の execute 1回のみ
        assert db.execute.call_count == 1


class TestRegisterWebhook:
    @pytest.mark.asyncio
    async def test_skips_when_google_not_connected(self):
        """Google 未接続（RuntimeError）のときは None を返す。"""
        from app.services.google_webhook import register_webhook
        db = _make_db()
        with patch("app.services.google_calendar._get_service",
                   AsyncMock(side_effect=RuntimeError("not connected"))):
            result = await register_webhook(db, tenant_id=1)
            assert result is None

    @pytest.mark.asyncio
    async def test_skips_when_watch_fails(self):
        """events().watch().execute() 失敗時は None を返す。"""
        from app.services.google_webhook import register_webhook

        mock_service = MagicMock()
        mock_service.events().watch().execute.side_effect = Exception("API error")

        db = _make_db()
        with patch("app.services.google_calendar._get_service",
                   AsyncMock(return_value=mock_service)):
            result = await register_webhook(db, tenant_id=1)
            assert result is None


class TestStopWebhook:
    @pytest.mark.asyncio
    async def test_returns_early_when_no_subscription(self):
        """サブスクリプションが存在しない場合は早期 return。"""
        from app.services.google_webhook import stop_webhook
        db = _make_db(first_return=None)
        await stop_webhook(db, tenant_id=1)
        # commit は呼ばれない（DELETE も実行されない）
        db.commit.assert_not_called()

    @pytest.mark.asyncio
    async def test_stops_and_deletes_subscription(self):
        """サブスクリプションが存在する場合は Google チャンネルを停止して DB から削除。"""
        from app.services.google_webhook import stop_webhook

        mock_service = MagicMock()
        mock_service.channels().stop().execute = MagicMock()

        db = AsyncMock()
        db.commit = AsyncMock()

        sub_result = MagicMock()
        sub_result.first = MagicMock(return_value=("ch_abc", "res_xyz"))
        delete_result = MagicMock()
        db.execute = AsyncMock(side_effect=[sub_result, delete_result])

        with patch("app.services.google_calendar._get_service",
                   AsyncMock(return_value=mock_service)):
            await stop_webhook(db, tenant_id=1)
        db.commit.assert_called()


class TestRenewExpiringWebhooks:
    @pytest.mark.asyncio
    async def test_returns_zero_when_no_expiring(self):
        """更新対象がない場合は 0 を返す。"""
        from app.services.google_webhook import renew_expiring_webhooks
        db = _make_db(fetchall_return=[])
        result = await renew_expiring_webhooks(db)
        assert result == 0

    @pytest.mark.asyncio
    async def test_renews_expiring_channel(self):
        """有効期限が近い場合は register_webhook を呼ぶ（Google 未接続で None = renewed=0）。"""
        from app.services.google_webhook import renew_expiring_webhooks

        db = AsyncMock()
        db.commit = AsyncMock()

        expiring_result = MagicMock()
        expiring_result.fetchall = MagicMock(return_value=[(1,)])  # tenant_id=1
        # register_webhook 内で _get_sync_mode を DB に問い合わせる → RuntimeError を出してスキップ
        # _get_service は RuntimeError → register_webhook は None を返す → renewed=0
        sub_result = MagicMock()
        sub_result.first = MagicMock(return_value=None)
        db.execute = AsyncMock(side_effect=[expiring_result, sub_result])

        with patch("app.services.google_calendar._get_service",
                   AsyncMock(side_effect=RuntimeError("not connected"))):
            result = await renew_expiring_webhooks(db)
        # Google 未接続 → None が返る → renewed は 0
        assert result == 0


class TestHandleWebhookNotificationExists:
    @pytest.mark.asyncio
    async def test_handles_exists_state_google_not_connected(self):
        """exists 状態でテナントが見つかっても Google 未接続なら早期 return。"""
        from app.services.google_webhook import handle_webhook_notification

        db = AsyncMock()
        db.commit = AsyncMock()

        channel_result = MagicMock()
        channel_result.first = MagicMock(return_value=(1,))  # tenant found
        schema_result = MagicMock()
        db.execute = AsyncMock(side_effect=[channel_result, schema_result])

        with patch("app.services.google_calendar._get_service",
                   AsyncMock(side_effect=RuntimeError("not connected"))):
            await handle_webhook_notification(db, channel_id="ch_123", resource_state="exists")
