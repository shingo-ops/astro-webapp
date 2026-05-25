from __future__ import annotations

"""
アプリ内カレンダーサービス。

担当範囲:
  - calendar_events テーブルの CRUD（テナントスキーマ）
  - Google Calendar との双方向同期ロジック
    - App → Google: イベント作成/更新/削除時に Google Calendar API を呼び出し
    - Google → App: Webhook 受信時の upsert（upsert_from_google）
  - 無限ループ防止: sync_origin_id による起源判定

設計判断:
  - calendar_events はテナントスキーマに配置（get_current_tenant で search_path 設定済み）
  - Google Calendar API は google_calendar サービスに委譲
  - sync_mode に応じて Google 同期の有無を切り替え
"""

import logging
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 内部ヘルパー
# ---------------------------------------------------------------------------


async def _get_sync_mode(db: AsyncSession, tenant_id: int) -> str:
    """テナントの同期モードを返す。Google 未接続の場合は 'none' を返す。"""
    row = await db.execute(
        text(
            "SELECT sync_mode FROM tenant_google_calendar_config WHERE tenant_id = :tid"
        ),
        {"tid": tenant_id},
    )
    record = row.first()
    return record[0] if record else "none"


def _build_sync_origin_id(tenant_id: int, calendar_event_id: int) -> str:
    """アプリ起源のイベントを識別する sync_origin_id を生成する。
    Webhook 受信時にこの値が存在するイベントはスキップして無限ループを防止する。
    """
    return f"app:{tenant_id}:{calendar_event_id}"


async def _is_app_origin(
    db: AsyncSession, google_event_id: str, tenant_id: int
) -> bool:
    """google_event_id がアプリ起源かどうかを判定する（無限ループ防止）。"""
    row = await db.execute(
        text(
            "SELECT 1 FROM calendar_events"
            " WHERE google_event_id = :gid"
            " AND sync_origin_id LIKE 'app:" + str(tenant_id) + ":%'"
            " LIMIT 1"
        ),
        {"gid": google_event_id},
    )
    return row.first() is not None


# ---------------------------------------------------------------------------
# イベント一覧取得
# ---------------------------------------------------------------------------


async def list_events(
    db: AsyncSession,
    tenant_id: int,
    start: str,
    end: str,
    calendar_type: Optional[str] = None,
    user_id: Optional[int] = None,
) -> list[dict]:
    """期間・タイプでカレンダーイベントを取得する。

    calendar_type が 'shared' の場合は全ユーザーのイベント。
    calendar_type が 'personal' の場合は user_id のイベントのみ。
    """
    filters = [
        "start_datetime < :end",
        "end_datetime > :start",
    ]
    params: dict = {"start": start, "end": end}

    if calendar_type == "shared":
        filters.append("calendar_type = 'shared'")
    elif calendar_type == "personal" and user_id:
        filters.append("calendar_type = 'personal'")
        filters.append("user_id = :uid")
        params["uid"] = user_id

    where = " AND ".join(filters)
    result = await db.execute(
        text(
            f"SELECT id, user_id, calendar_type, title, description, location,"
            f" start_datetime, end_datetime, is_all_day, google_event_id, source,"
            f" sync_status, created_by_user_id, created_at, updated_at"
            f" FROM calendar_events WHERE {where}"
            f" ORDER BY start_datetime"
        ),
        params,
    )
    rows = result.fetchall()
    return [
        {
            "id": r[0],
            "user_id": r[1],
            "calendar_type": r[2],
            "title": r[3],
            "description": r[4],
            "location": r[5],
            "start_datetime": r[6].isoformat() if r[6] else None,
            "end_datetime": r[7].isoformat() if r[7] else None,
            "is_all_day": r[8],
            "google_event_id": r[9],
            "source": r[10],
            "sync_status": r[11],
            "created_by_user_id": r[12],
            "created_at": r[13].isoformat() if r[13] else None,
            "updated_at": r[14].isoformat() if r[14] else None,
        }
        for r in rows
    ]


# ---------------------------------------------------------------------------
# イベント作成
# ---------------------------------------------------------------------------


async def create_event(
    db: AsyncSession,
    tenant_id: int,
    user_id: int,
    payload: dict,
) -> dict:
    """アプリ内にイベントを作成し、Google Calendar に同期する。

    同期モードが 'bidirectional' または 'write_only' の場合のみ Google に送信する。
    """
    # DB に保存（sync_status='pending' で開始）
    result = await db.execute(
        text(
            "INSERT INTO calendar_events"
            " (user_id, calendar_type, title, description, location,"
            "  start_datetime, end_datetime, is_all_day, source, sync_status,"
            "  created_by_user_id)"
            " VALUES"
            " (:uid, :ctype, :title, :desc, :loc,"
            "  :start, :end, :all_day, 'app', 'pending',"
            "  :cuid)"
            " RETURNING id"
        ),
        {
            "uid": user_id if payload.get("calendar_type") == "personal" else None,
            "ctype": payload.get("calendar_type", "shared"),
            "title": payload["title"],
            "desc": payload.get("description"),
            "loc": payload.get("location"),
            "start": payload["start_datetime"],
            "end": payload["end_datetime"],
            "all_day": payload.get("is_all_day", False),
            "cuid": user_id,
        },
    )
    event_id = result.scalar_one()
    await db.commit()

    # Google Calendar に同期
    sync_mode = await _get_sync_mode(db, tenant_id)
    if sync_mode in ("bidirectional", "write_only"):
        try:
            from app.services import google_calendar as cal_svc

            google_body = _to_google_event_body(payload)
            google_event = await cal_svc.create_event(db, tenant_id, google_body)
            google_event_id = google_event.get("id")

            origin_id = _build_sync_origin_id(tenant_id, event_id)
            await db.execute(
                text(
                    "UPDATE calendar_events"
                    " SET google_event_id = :gid, sync_origin_id = :oid,"
                    "     sync_status = 'synced', last_synced_at = NOW()"
                    " WHERE id = :id"
                ),
                {"gid": google_event_id, "oid": origin_id, "id": event_id},
            )
            await db.commit()
        except Exception as e:
            logger.warning("Google Calendar 同期に失敗しました (event_id=%s): %s", event_id, e)
            await db.execute(
                text(
                    "UPDATE calendar_events SET sync_status = 'failed' WHERE id = :id"
                ),
                {"id": event_id},
            )
            await db.commit()

    return {"id": event_id}


# ---------------------------------------------------------------------------
# イベント更新
# ---------------------------------------------------------------------------


async def update_event(
    db: AsyncSession,
    tenant_id: int,
    event_id: int,
    user_id: int,
    payload: dict,
) -> dict:
    """アプリ内のイベントを更新し、Google Calendar に同期する。"""
    # DB 更新
    set_clauses = []
    params: dict = {"id": event_id}

    field_map = {
        "title": "title",
        "description": "description",
        "location": "location",
        "start_datetime": "start_datetime",
        "end_datetime": "end_datetime",
        "is_all_day": "is_all_day",
    }
    for k, col in field_map.items():
        if k in payload:
            set_clauses.append(f"{col} = :{k}")
            params[k] = payload[k]

    if not set_clauses:
        return {"id": event_id}

    set_clauses.append("sync_status = 'pending'")
    set_sql = ", ".join(set_clauses)
    await db.execute(
        text(f"UPDATE calendar_events SET {set_sql} WHERE id = :id"),
        params,
    )
    await db.commit()

    # Google Calendar に同期
    row = await db.execute(
        text("SELECT google_event_id FROM calendar_events WHERE id = :id"),
        {"id": event_id},
    )
    record = row.first()
    google_event_id = record[0] if record else None

    sync_mode = await _get_sync_mode(db, tenant_id)
    if google_event_id and sync_mode in ("bidirectional", "write_only"):
        try:
            from app.services import google_calendar as cal_svc

            google_body = _to_google_event_body(payload)
            await cal_svc.update_event(db, tenant_id, google_event_id, google_body)
            await db.execute(
                text(
                    "UPDATE calendar_events"
                    " SET sync_status = 'synced', last_synced_at = NOW()"
                    " WHERE id = :id"
                ),
                {"id": event_id},
            )
            await db.commit()
        except Exception as e:
            logger.warning("Google Calendar 更新同期に失敗 (event_id=%s): %s", event_id, e)
            await db.execute(
                text("UPDATE calendar_events SET sync_status = 'failed' WHERE id = :id"),
                {"id": event_id},
            )
            await db.commit()

    return {"id": event_id}


# ---------------------------------------------------------------------------
# イベント削除
# ---------------------------------------------------------------------------


async def delete_event(
    db: AsyncSession,
    tenant_id: int,
    event_id: int,
) -> None:
    """アプリ内のイベントを削除し、Google Calendar からも削除する。"""
    row = await db.execute(
        text("SELECT google_event_id FROM calendar_events WHERE id = :id"),
        {"id": event_id},
    )
    record = row.first()
    google_event_id = record[0] if record else None

    await db.execute(
        text("DELETE FROM calendar_events WHERE id = :id"),
        {"id": event_id},
    )
    await db.commit()

    sync_mode = await _get_sync_mode(db, tenant_id)
    if google_event_id and sync_mode in ("bidirectional", "write_only"):
        try:
            from app.services import google_calendar as cal_svc

            await cal_svc.delete_event(db, tenant_id, google_event_id)
        except Exception as e:
            logger.warning("Google Calendar 削除同期に失敗 (event_id=%s): %s", event_id, e)


# ---------------------------------------------------------------------------
# Webhook 受信時の upsert
# ---------------------------------------------------------------------------


async def upsert_from_google(
    db: AsyncSession,
    tenant_id: int,
    google_event: dict,
) -> None:
    """Google Calendar Webhook 受信時にイベントを DB に upsert する。

    無限ループ防止:
      - sync_origin_id が "app:tenant_id:*" で始まるイベントはアプリ起源なのでスキップ。
      - これにより「アプリ → Google → Webhook → アプリ → ...」の無限ループを防ぐ。
    """
    google_event_id = google_event.get("id")
    if not google_event_id:
        return

    # アプリ起源のイベントか確認（ループ防止）
    if await _is_app_origin(db, google_event_id, tenant_id):
        logger.debug("スキップ（アプリ起源）: google_event_id=%s", google_event_id)
        return

    # 削除済みイベントの処理
    if google_event.get("status") == "cancelled":
        await db.execute(
            text(
                "DELETE FROM calendar_events WHERE google_event_id = :gid"
            ),
            {"gid": google_event_id},
        )
        await db.commit()
        return

    title = google_event.get("summary", "")
    description = google_event.get("description")
    location = google_event.get("location")
    is_all_day = "date" in (google_event.get("start") or {})

    start_raw = (google_event.get("start") or {})
    end_raw = (google_event.get("end") or {})
    start_dt = start_raw.get("dateTime") or start_raw.get("date")
    end_dt = end_raw.get("dateTime") or end_raw.get("date")

    if not start_dt or not end_dt:
        logger.warning("start/end が不正: google_event_id=%s", google_event_id)
        return

    origin_id = f"google:{tenant_id}:{google_event_id}"

    await db.execute(
        text(
            "INSERT INTO calendar_events"
            " (calendar_type, title, description, location,"
            "  start_datetime, end_datetime, is_all_day,"
            "  google_event_id, google_calendar_id, source, sync_status,"
            "  sync_origin_id, last_synced_at)"
            " VALUES"
            " ('shared', :title, :desc, :loc,"
            "  :start, :end, :all_day,"
            "  :gid, :gcal_id, 'google', 'synced',"
            "  :origin, NOW())"
            " ON CONFLICT (google_event_id) DO UPDATE SET"
            "   title            = EXCLUDED.title,"
            "   description      = EXCLUDED.description,"
            "   location         = EXCLUDED.location,"
            "   start_datetime   = EXCLUDED.start_datetime,"
            "   end_datetime     = EXCLUDED.end_datetime,"
            "   is_all_day       = EXCLUDED.is_all_day,"
            "   sync_status      = 'synced',"
            "   last_synced_at   = NOW()"
            " WHERE calendar_events.google_event_id = :gid"
        ),
        {
            "title": title,
            "desc": description,
            "loc": location,
            "start": start_dt,
            "end": end_dt,
            "all_day": is_all_day,
            "gid": google_event_id,
            "gcal_id": "primary",
            "origin": origin_id,
        },
    )
    await db.commit()


# ---------------------------------------------------------------------------
# Google Calendar API 用ボディ変換
# ---------------------------------------------------------------------------


def _to_google_event_body(payload: dict) -> dict:
    """アプリのイベント payload を Google Calendar API 用ボディに変換する。"""
    body: dict = {
        "summary": payload.get("title", ""),
    }

    start_dt = payload.get("start_datetime", "")
    end_dt = payload.get("end_datetime", "")

    if payload.get("is_all_day"):
        body["start"] = {"date": str(start_dt)[:10]}
        body["end"] = {"date": str(end_dt)[:10]}
    else:
        body["start"] = {"dateTime": start_dt, "timeZone": "Asia/Tokyo"}
        body["end"] = {"dateTime": end_dt, "timeZone": "Asia/Tokyo"}

    if payload.get("description"):
        body["description"] = payload["description"]
    if payload.get("location"):
        body["location"] = payload["location"]

    return body
