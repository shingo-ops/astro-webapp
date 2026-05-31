"""Discord Bot Gateway client (ADR-009 M3).

Sprint 5 (F5) で M2 から M3 に拡張:
  - `on_message` を実装し、`public.supplier_discord_routing` で照合した
    メッセージを `public.discord_inbound_messages` に冪等保存する。
  - 未登録 guild/channel は `parse_status='ignored_routing'` で保存し、
    F3 解析は走らせない (AC5.3)。
  - 登録済の場合は `inventory_parser.parse_inventory_message` を
    `asyncio.create_task` で fire-and-forget で起動する (spec L157)。
  - `on_resumed` で、切断中に取り逃したメッセージを REST `channel.history()`
    で補完取得し、漏れなく `discord_inbound_messages` に追加する (AC5.4)。

参照:
  - .claude-pipeline/spec.md F5 AC5.1〜5.5
  - backend/app/discord_gateway/inbound_writer.py (DB I/O ヘルパ)
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any, Callable

import discord

from app.discord_gateway import dm_writer, inbound_writer
from app.discord_gateway.config import TenantBotConfig

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# JarvisDiscordClient (M3)
# ---------------------------------------------------------------------------


class JarvisDiscordClient(discord.Client):
    """ADR-009 M3: MESSAGE_CREATE / RESUMED ハンドラ実装版。

    - on_message:    routing 照合 → 冪等 INSERT → parse タスク投入
    - on_resumed:    missed messages を REST history で補完
    - on_disconnect: warning ログのみ（再接続は discord.py に任せる）
    """

    def __init__(
        self,
        tenant: TenantBotConfig,
        *,
        db_factory: Callable[[], Any] | None = None,
    ) -> None:
        """Args:
            tenant: TenantBotConfig
            db_factory: AsyncSession factory (テスト時に差し込み可能)。
                None なら `app.database.AsyncSessionLocal` を遅延 import。
        """
        intents = discord.Intents.none()
        intents.guilds = True
        intents.guild_messages = True
        intents.dm_messages = True
        intents.message_content = True
        intents.members = True
        super().__init__(intents=intents)
        self.tenant = tenant
        self._db_factory_override = db_factory
        # 補完済 channel_id を記録（resumed で重複補完しないため）
        self._resumed_completed: set[str] = set()

    # --- helpers ---------------------------------------------------------

    def _db_factory(self) -> Any:
        if self._db_factory_override is not None:
            return self._db_factory_override
        # 遅延 import: 起動時 DB 接続コストを避ける
        from app.database import AsyncSessionLocal
        return AsyncSessionLocal

    # --- event handlers --------------------------------------------------

    async def on_ready(self) -> None:
        user = self.user
        logger.info(
            "[discord-gateway] READY tenant=%s tenant_id=%d bot=%s#%s id=%s guilds=%d",
            self.tenant.tenant_code,
            self.tenant.tenant_id,
            user.name if user else "?",
            user.discriminator if user else "?",
            user.id if user else "?",
            len(self.guilds),
        )

    async def on_resumed(self) -> None:
        """切断 → 再接続後の missed messages を補完 (AC5.4)。

        - 全 guild × text channel を走査
        - 各 channel の MAX(received_at) を取得し、それ以降を REST history で取得
        - 通常の on_message と同じ経路で処理する（routing 照合 + 冪等 INSERT）
        """
        logger.info(
            "[discord-gateway] RESUMED tenant=%s tenant_id=%d — fetching missed messages",
            self.tenant.tenant_code,
            self.tenant.tenant_id,
        )
        await self._resume_missed_messages()

    async def on_disconnect(self) -> None:
        logger.warning(
            "[discord-gateway] DISCONNECT tenant=%s tenant_id=%d",
            self.tenant.tenant_code,
            self.tenant.tenant_id,
        )

    async def on_message(self, message: discord.Message) -> None:  # type: ignore[override]
        """MESSAGE_CREATE: DM は顧客受信箱経路、guild は仕入元解析経路へ振り分ける。

        DM (guild=None):
          _process_dm_message → dm_writer → {schema}.meta_messages (platform='discord')

        Guild メッセージ:
          _process_message → inbound_writer → public.discord_inbound_messages (在庫解析)

        AC5.1: 受信から 5 秒以内に discord_inbound_messages 1 行追加
        AC5.2: 同一 discord_message_id 2 回 → 1 行のみ
        AC5.3: routing 未登録 guild → parse_status='ignored_routing'、解析走らない
        """
        # Bot 自身 / 他 Bot は無視
        if getattr(message.author, "bot", False):
            return
        if message.guild is None:
            # DM → 顧客メッセージング（受信箱）経路
            await self._process_dm_message(message)
        else:
            # Guild チャンネル → 仕入元在庫解析経路（既存）
            await self._process_message(message)

    # --- internal --------------------------------------------------------

    async def _process_dm_message(self, message: discord.Message) -> None:
        """DM メッセージを受信箱へ記録する（顧客向けメッセージング経路）。

        leads テーブルで discord_user_id による lead upsert を行い、
        meta_messages に platform='discord', direction='inbound' で INSERT する。
        SSE で受信箱フロントエンドに通知する。
        """
        discord_user_id = str(message.author.id)
        dm_channel_id = str(message.channel.id)
        sender_name = getattr(message.author, "display_name", "") or str(message.author)
        tenant_id = self.tenant.tenant_id

        db_factory = self._db_factory()
        try:
            async with db_factory() as session:  # type: ignore[misc]
                await dm_writer.upsert_lead_and_message(
                    session,
                    tenant_id=tenant_id,
                    discord_user_id=discord_user_id,
                    sender_name=sender_name,
                    dm_channel_id=dm_channel_id,
                    message_text=message.content or "",
                    discord_message_id=str(message.id),
                    created_at=message.created_at,
                )
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            logger.exception(
                "[discord-gateway] DM 受信箱記録失敗 tenant=%s user=%s msg=%s: %s",
                self.tenant.tenant_code, discord_user_id, message.id, exc,
            )
            return

        # SSE で受信箱フロントエンドに通知（失敗しても DM 処理は継続）
        try:
            from app.services.sse_pubsub import publish_inbox_update
            await publish_inbox_update(tenant_id)
        except Exception:  # noqa: BLE001
            logger.debug("[discord-gateway] SSE publish スキップ（設定なし）")

    async def _process_message(self, message: discord.Message) -> None:
        payload = inbound_writer.message_to_inbound_payload(message)
        guild_id = payload["discord_guild_id"]
        channel_id = payload["discord_channel_id"]
        msg_id = payload["discord_message_id"]
        raw = payload["raw_content"]
        received_at = payload["received_at"]

        db_factory = self._db_factory()
        async with db_factory() as session:  # type: ignore[misc]
            routing = None
            if guild_id and channel_id:
                routing = await inbound_writer.lookup_routing(
                    session, guild_id=guild_id, channel_id=channel_id
                )

            if routing is None:
                # AC5.3: routing 未登録 → ignored_routing で記録、解析しない
                ins = await inbound_writer.write_inbound(
                    session,
                    discord_message_id=msg_id,
                    discord_channel_id=channel_id or "",
                    supplier_id=None,
                    raw_content=raw,
                    parse_status="ignored_routing",
                    received_at=received_at,
                )
                if ins.inserted:
                    logger.info(
                        "[discord-gateway] ignored_routing tenant=%s msg_id=%s ch=%s",
                        self.tenant.tenant_code,
                        msg_id,
                        channel_id,
                    )
                return

            # AC5.1/AC5.2: routing 登録済 → pending で INSERT → 解析投入
            ins = await inbound_writer.write_inbound(
                session,
                discord_message_id=msg_id,
                discord_channel_id=channel_id,
                supplier_id=routing.supplier_id,
                raw_content=raw,
                parse_status="pending",
                received_at=received_at,
            )

        if not ins.inserted:
            # AC5.2: 既存メッセージ。解析を再投入しない (冪等)
            logger.debug(
                "[discord-gateway] duplicate msg_id=%s skip parse task",
                msg_id,
            )
            return

        # 解析タスク投入 (fire-and-forget)
        assert ins.inbound_id is not None
        await inbound_writer.schedule_parse(
            db_factory=db_factory,
            inbound_id=ins.inbound_id,
            raw_content=raw,
            supplier_id=routing.supplier_id,
            language=routing.default_language,
            tenant_id=self.tenant.tenant_id,
        )

    async def _resume_missed_messages(self) -> None:
        """全 guild × text channel について REST history で補完。"""
        db_factory = self._db_factory()
        for guild in self.guilds:
            for channel in guild.text_channels:
                ch_id = str(channel.id)
                try:
                    async with db_factory() as session:  # type: ignore[misc]
                        last_at = (
                            await inbound_writer.get_last_received_at_for_channel(
                                session, ch_id
                            )
                        )
                    missed = await inbound_writer.fetch_missed_messages(
                        channel, after=last_at, limit=100
                    )
                except asyncio.CancelledError:
                    raise
                except Exception as exc:  # noqa: BLE001
                    logger.warning(
                        "[discord-gateway] resume fetch failed tenant=%s ch=%s: %s",
                        self.tenant.tenant_code,
                        ch_id,
                        exc,
                    )
                    continue
                for m in missed:
                    if getattr(m.author, "bot", False):
                        continue
                    try:
                        await self._process_message(m)
                    except Exception as exc:  # noqa: BLE001
                        logger.warning(
                            "[discord-gateway] resume process failed msg_id=%s: %s",
                            getattr(m, "id", "?"),
                            exc,
                        )


_MAX_RECONNECT_ATTEMPTS = 10


async def run_gateway(tenant: TenantBotConfig) -> None:
    """1 テナント分の Gateway 接続を維持する。切断時は discord.py が自動再接続する。

    LoginFailure は致命的（Token 不正/失効）として例外を re-raise する。
    main 側で全テナント致命時に非ゼロ終了する。

    一般例外は指数バックオフで再起動（最大 60 秒）。
    _MAX_RECONNECT_ATTEMPTS 回連続失敗したら停止してアラートを発報する。
    """
    backoff = 5
    max_backoff = 60
    reconnect_count = 0
    while True:
        client = JarvisDiscordClient(tenant)
        try:
            await client.start(tenant.bot_token, reconnect=True)
        except discord.LoginFailure:
            logger.critical(
                "[discord-gateway] LoginFailure tenant=%s — Token 不正/失効。"
                "Discord Developer Portal で Token を再発行し GitHub Secrets を更新すること",
                tenant.tenant_code,
            )
            raise
        except asyncio.CancelledError:
            logger.info("[discord-gateway] CancelledError tenant=%s", tenant.tenant_code)
            await client.close()
            raise
        except Exception as exc:
            reconnect_count += 1
            logger.exception(
                "[discord-gateway] 例外発生 tenant=%s exc_type=%s, %d 秒後に再起動 (attempt %d/%d)",
                tenant.tenant_code,
                type(exc).__name__,
                backoff,
                reconnect_count,
                _MAX_RECONNECT_ATTEMPTS,
            )
            if reconnect_count >= _MAX_RECONNECT_ATTEMPTS:
                logger.critical(
                    "[discord-gateway] 最大再接続回数 (%d) を超えました tenant=%s — "
                    "手動で Bot Token を確認し再起動してください",
                    _MAX_RECONNECT_ATTEMPTS,
                    tenant.tenant_code,
                )
                raise RuntimeError(
                    f"Discord gateway max reconnect attempts reached for tenant={tenant.tenant_code}"
                ) from exc
            try:
                await client.close()
            except Exception:
                pass
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, max_backoff)
        else:
            backoff = 5
            reconnect_count = 0
