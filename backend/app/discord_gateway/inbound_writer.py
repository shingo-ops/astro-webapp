"""
spec.md v1.1 F5 / Sprint 5: Discord Gateway 受信メッセージの DB 書き込み補助。

このモジュールは `discord_gateway/client.py` の `on_message` ハンドラが呼び出す
DB I/O ヘルパを集約する。client.py を thin に保ち、テストでは pure な non-discord
入力（discord.Message を mock した dict）で検証できるよう、Discord SDK への直接
依存を **薄い adapter 関数** に閉じ込めている。

### 設計判断 (PR description に明示)

1. **冪等性の実装**: AC5.2 の「同一 discord_message_id を 2 回受信 → 1 行のみ」は
   `public.discord_inbound_messages.discord_message_id UNIQUE` 制約 + INSERT
   ... ON CONFLICT (discord_message_id) DO NOTHING RETURNING id で担保する。
   仕様 (spec L159) は「冪等性は discord_webhook_idempotency で保証」と述べるが、
   discord_webhook_idempotency は **HTTP webhook** 用設計（message_id VARCHAR(100)、
   payload_hash あり）であり、Bot Gateway 経由 (WebSocket) の `MESSAGE_CREATE`
   イベントには適さない。

   ただし「監査ログ」の意味は残るため、Gateway 経路でも
   `discord_webhook_idempotency` には INSERT する（冪等担保の **主体は
   discord_inbound_messages の UNIQUE 制約**、idempotency 表は **観測用 audit**）。

2. **解析キュー方式**: `asyncio.create_task(parse_and_update_status(...))` で
   fire-and-forget。spec L157 「in-process 非同期 task」と完全一致。例外は
   parse_and_update_status 内で握り、parse_status='unparsed' / 'budget_exhausted' /
   独自 'parse_error' のいずれかに更新する。Celery / Redis Queue は v1.1 の
   範囲外（規模拡大時の別 ADR 候補）。

3. **parse_error enum 値**: 既存 CHECK 制約 (migration 059) には 'parse_error' が
   ない。`unparsed` を流用する（rule_v1 / LLM 双方失敗時の意味と整合）。
   将来 'parse_error' を追加する場合は migration 067 で CHECK 拡張。

4. **missed messages 補完 (AC5.4)**: discord.py `channel.history(after=last_seen)`
   で REST 経由で取得。Rate limit は discord.py が自動で respect する。
   `last_seen` は `MAX(received_at)` を per-channel で取得（DB 1 クエリ）。

参照:
  - .claude-pipeline/spec.md F5 AC5.1〜5.5
  - migrations/059_create_discord_inbound_messages.sql
  - migrations/060_create_supplier_discord_routing.sql
  - backend/app/services/inventory_parser.py (parse_inventory_message)
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Protocol

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Types
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SupplierRouting:
    """public.supplier_discord_routing の 1 行。

    Discord SDK の Message から guild_id / channel_id を抽出 → このオブジェクトを
    返す。is_active=false の行は lookup で None を返す（routing 未登録扱い）。
    """

    routing_id: int
    supplier_id: int
    discord_guild_id: str
    discord_channel_id: str
    is_active: bool
    default_language: str  # JOIN: public.suppliers.default_language


@dataclass(frozen=True)
class InboundInsertResult:
    """write_inbound の結果。"""

    inbound_id: int | None  # 新規 INSERT 時は ID、既存（duplicate）時は None
    inserted: bool          # True = 新規投入、False = 既存だった (idempotency hit)


# ---------------------------------------------------------------------------
# discord.Message Protocol（テストで mock しやすいよう duck typing）
# ---------------------------------------------------------------------------


class _DiscordMessageLike(Protocol):
    """discord.Message のうち本モジュールが使うフィールドだけを切り出した型。

    実体は `discord.Message` だが、テストでは plain object / dataclass で代用可能。
    """

    @property
    def id(self) -> int: ...

    @property
    def content(self) -> str: ...

    @property
    def guild(self) -> Any: ...  # discord.Guild | None

    @property
    def channel(self) -> Any: ...  # discord.TextChannel

    @property
    def author(self) -> Any: ...  # discord.User / Member

    @property
    def created_at(self) -> datetime: ...


# ---------------------------------------------------------------------------
# DB ops
# ---------------------------------------------------------------------------


async def lookup_routing(
    db: AsyncSession,
    guild_id: str,
    channel_id: str,
) -> SupplierRouting | None:
    """guild_id / channel_id から routing 行を取得。is_active=false なら None。

    JOIN public.suppliers で default_language も同時取得（解析時の言語決定）。

    Args:
        db: AsyncSession
        guild_id: Discord guild snowflake (string で扱う、64bit int 安全)
        channel_id: Discord channel snowflake

    Returns:
        SupplierRouting if found and active, else None.
    """
    result = await db.execute(
        text(
            """
            SELECT r.id            AS routing_id,
                   r.supplier_id,
                   r.discord_guild_id,
                   r.discord_channel_id,
                   r.is_active,
                   COALESCE(s.default_language, 'ja') AS default_language
              FROM public.supplier_discord_routing r
              LEFT JOIN public.suppliers s ON s.id = r.supplier_id
             WHERE r.discord_guild_id = :guild
               AND r.discord_channel_id = :channel
               AND r.is_active = TRUE
             LIMIT 1
            """
        ),
        {"guild": guild_id, "channel": channel_id},
    )
    row = result.mappings().first()
    if row is None:
        return None
    return SupplierRouting(
        routing_id=row["routing_id"],
        supplier_id=row["supplier_id"],
        discord_guild_id=row["discord_guild_id"],
        discord_channel_id=row["discord_channel_id"],
        is_active=row["is_active"],
        default_language=row["default_language"],
    )


async def write_inbound(
    db: AsyncSession,
    *,
    discord_message_id: str,
    discord_channel_id: str,
    supplier_id: int | None,
    raw_content: str,
    parse_status: str = "pending",
    received_at: datetime | None = None,
) -> InboundInsertResult:
    """public.discord_inbound_messages に冪等 INSERT。

    AC5.2: 同一 discord_message_id を 2 回呼んでも 1 行のみ。
            ON CONFLICT (discord_message_id) DO NOTHING で担保。

    audit: public.discord_webhook_idempotency にも INSERT (監査用、冪等)。

    Args:
        supplier_id: None なら routing 未登録扱い (parse_status='ignored_routing')
        parse_status: 'pending' / 'ignored_routing' / ... (CHECK 制約 migration 059)

    Returns:
        InboundInsertResult: inserted=False なら既存重複だった。
    """
    received_at = received_at or datetime.now(timezone.utc)

    # AC5.2 主体: discord_inbound_messages.discord_message_id UNIQUE
    result = await db.execute(
        text(
            """
            INSERT INTO public.discord_inbound_messages
                (discord_message_id, discord_channel_id, supplier_id,
                 raw_content, parse_status, received_at)
            VALUES
                (:msg_id, :ch_id, :sup_id, :raw, :status, :rcv)
            ON CONFLICT (discord_message_id) DO NOTHING
            RETURNING id
            """
        ),
        {
            "msg_id": discord_message_id,
            "ch_id": discord_channel_id,
            "sup_id": supplier_id,
            "raw": raw_content,
            "status": parse_status,
            "rcv": received_at,
        },
    )
    row = result.first()
    if row is None:
        # 既存メッセージ。idempotency 表だけ更新（audit、初回 hit を記録）
        await _record_idempotency_audit(
            db,
            discord_message_id=discord_message_id,
            raw_content=raw_content,
            result_status="duplicate",
        )
        await db.commit()
        return InboundInsertResult(inbound_id=None, inserted=False)

    inbound_id = int(row[0])

    # audit: idempotency 表に初回投入を記録
    await _record_idempotency_audit(
        db,
        discord_message_id=discord_message_id,
        raw_content=raw_content,
        result_status="accepted",
    )

    await db.commit()
    return InboundInsertResult(inbound_id=inbound_id, inserted=True)


async def _record_idempotency_audit(
    db: AsyncSession,
    *,
    discord_message_id: str,
    raw_content: str,
    result_status: str,
) -> None:
    """public.discord_webhook_idempotency へ audit 行を INSERT (冪等)。

    冪等性は discord_inbound_messages 側で担保しているので、本表は **観測用 audit**。
    UNIQUE(message_id) で重複時は DO NOTHING。
    """
    payload_hash = hashlib.sha256(raw_content.encode("utf-8")).hexdigest()
    await db.execute(
        text(
            """
            INSERT INTO public.discord_webhook_idempotency
                (message_id, payload_hash, processed_at, result_status)
            VALUES
                (:mid, :ph, NOW(), :rs)
            ON CONFLICT (message_id) DO NOTHING
            """
        ),
        {"mid": discord_message_id, "ph": payload_hash, "rs": result_status},
    )


async def get_last_received_at_for_channel(
    db: AsyncSession,
    channel_id: str,
) -> datetime | None:
    """指定 channel における最新 received_at を返す (AC5.4 missed messages 補完用)。

    None なら過去の受信ゼロ → 全件補完。
    """
    result = await db.execute(
        text(
            """
            SELECT MAX(received_at) AS last_at
              FROM public.discord_inbound_messages
             WHERE discord_channel_id = :ch
            """
        ),
        {"ch": channel_id},
    )
    row = result.first()
    if row is None or row[0] is None:
        return None
    val = row[0]
    if isinstance(val, datetime):
        return val
    return None


async def update_parse_result(
    db: AsyncSession,
    inbound_id: int,
    *,
    parse_status: str,
    parse_engine: str | None,
    parse_result_json: Any,
    llm_cost_usd: Any = None,
) -> None:
    """解析結果を discord_inbound_messages に書き戻す。

    parse_inventory_message の戻り ParseResult を呼び出し側でこのヘルパに渡す。
    JSONB は psycopg/asyncpg で dict → jsonb 自動変換される。
    """
    await db.execute(
        text(
            """
            UPDATE public.discord_inbound_messages
               SET parse_status      = :status,
                   parse_engine      = :engine,
                   parse_result_json = CAST(:result_json AS JSONB),
                   llm_cost_usd      = COALESCE(:cost, llm_cost_usd)
             WHERE id = :id
            """
        ),
        {
            "status": parse_status,
            "engine": parse_engine,
            "result_json": _to_json_str(parse_result_json),
            "cost": str(llm_cost_usd) if llm_cost_usd is not None else None,
            "id": inbound_id,
        },
    )
    await db.commit()


def _to_json_str(value: Any) -> str | None:
    if value is None:
        return None
    import json

    try:
        return json.dumps(value, default=str, ensure_ascii=False)
    except Exception:  # noqa: BLE001
        return json.dumps({"_repr": repr(value)}, ensure_ascii=False)


# ---------------------------------------------------------------------------
# Discord SDK adapter（テストで mock）
# ---------------------------------------------------------------------------


def message_to_inbound_payload(message: _DiscordMessageLike) -> dict[str, Any]:
    """`discord.Message` → write_inbound() に渡せる dict。

    Bot 自身のメッセージは呼び出し側で除外（is_bot 等は client.py 側で判定）。
    """
    guild = getattr(message, "guild", None)
    channel = getattr(message, "channel", None)
    return {
        "discord_message_id": str(message.id),
        "discord_guild_id": str(guild.id) if guild is not None else "",
        "discord_channel_id": str(channel.id) if channel is not None else "",
        "raw_content": message.content or "",
        "received_at": message.created_at,
    }


async def fetch_missed_messages(
    channel: Any,
    *,
    after: datetime | None,
    limit: int = 100,
) -> list[Any]:
    """REST `channel.history(after=after)` で missed messages を取得 (AC5.4)。

    Args:
        channel: discord.TextChannel (テストでは mock object)
        after: この時刻より新しいメッセージのみ。None なら最新 `limit` 件。
        limit: 上限。デフォルト 100 件（discord.py の REST page サイズ既定）。

    Returns:
        新→古 ではなく、`oldest_first=True` で古→新の順で返す（DB 投入順を安定化）。
    """
    msgs: list[Any] = []
    try:
        history = channel.history(after=after, limit=limit, oldest_first=True)
        async for m in history:
            msgs.append(m)
    except asyncio.CancelledError:
        raise
    except Exception as exc:  # noqa: BLE001 - 補完失敗は致命でない
        logger.warning(
            "[discord-gateway] fetch_missed_messages failed channel=%s after=%s: %s",
            getattr(channel, "id", "?"),
            after,
            exc,
        )
        return []
    return msgs


# ---------------------------------------------------------------------------
# 解析キュー投入 (fire-and-forget)
# ---------------------------------------------------------------------------


async def schedule_parse(
    *,
    db_factory: Any,  # Callable[[], AsyncContextManager[AsyncSession]]
    inbound_id: int,
    raw_content: str,
    supplier_id: int,
    language: str,
    tenant_id: int,
) -> asyncio.Task:
    """`parse_inventory_message` を asyncio.create_task で起動 (fire-and-forget)。

    AC5.1 / spec L157 「in-process 非同期 task」。例外は task 内で握り、
    parse_status を更新する。

    db_factory: 新しい AsyncSession を返す context manager factory。
        `app.database.AsyncSessionLocal` を想定（呼び出し側で渡す）。
        client.py から `db_factory=AsyncSessionLocal` で渡される。
    """

    async def _runner() -> None:
        # 局所 import: 循環参照防止 + Discord Gateway 起動時にテスト依存を増やさない
        from app.services.inventory_parser import parse_inventory_message

        try:
            async with db_factory() as session:  # type: ignore[misc]
                result = await parse_inventory_message(
                    session,
                    raw_content=raw_content,
                    supplier_id=supplier_id,
                    language=language,
                    tenant_id=tenant_id,
                )
                # parse_engine → parse_status マッピング
                # 参照: inventory_parser.parse_inventory_message docstring
                engine = result.parse_engine
                if engine == "rule_v1_fallback_blocked":
                    status_val = "budget_exhausted"
                elif engine in ("hybrid_rule_v1_llm_v1", "llm_supplier_prompt"):
                    # ADR-085: 仕入先別プロンプトによる全文 LLM 解析も LLM 由来
                    status_val = "parsed_llm"
                elif engine == "rule_v1":
                    # tenant_id 指定で unparsed なし or unparsed あり&LLM 不在
                    status_val = (
                        "parsed_rule_only" if not result.unparsed else "unparsed"
                    )
                else:
                    status_val = "parsed"

                await update_parse_result(
                    session,
                    inbound_id,
                    parse_status=status_val,
                    parse_engine=engine,
                    parse_result_json={
                        "items": [
                            _item_to_dict(it) for it in (result.items or [])
                        ],
                        "excludes": [
                            _item_to_dict(it) for it in (result.excludes or [])
                        ],
                        "unparsed": [
                            _item_to_dict(it) for it in (result.unparsed or [])
                        ],
                    },
                )
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            logger.exception(
                "[discord-gateway] parse task failed inbound_id=%s tenant=%s sup=%s: %s",
                inbound_id,
                tenant_id,
                supplier_id,
                exc,
            )
            try:
                async with db_factory() as session2:  # type: ignore[misc]
                    await update_parse_result(
                        session2,
                        inbound_id,
                        parse_status="unparsed",
                        parse_engine="rule_v1_failed",
                        parse_result_json={"error": str(exc)[:500]},
                    )
            except Exception:  # noqa: BLE001
                logger.warning(
                    "[discord-gateway] failed to update parse_status to unparsed after exception"
                )

    return asyncio.create_task(_runner(), name=f"discord-parse-{inbound_id}")


def _item_to_dict(it: Any) -> dict[str, Any]:
    """ParsedItem / ExcludeItem / UnparsedItem → dict (JSONB 投入用)。"""
    if hasattr(it, "model_dump"):
        return it.model_dump()
    if hasattr(it, "__dict__"):
        return {k: v for k, v in it.__dict__.items()}
    return {"value": str(it)}


__all__ = [
    "SupplierRouting",
    "InboundInsertResult",
    "lookup_routing",
    "write_inbound",
    "get_last_received_at_for_channel",
    "update_parse_result",
    "message_to_inbound_payload",
    "fetch_missed_messages",
    "schedule_parse",
]
