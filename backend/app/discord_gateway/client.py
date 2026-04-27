import asyncio
import logging

import discord

from app.discord_gateway.config import TenantBotConfig

logger = logging.getLogger(__name__)


class JarvisDiscordClient(discord.Client):
    """ADR-009 M2: Skeleton client。READY と heartbeat のみログ出力する。

    M3 で MESSAGE_CREATE → raw_webhook_events 投入を追加予定。
    """

    def __init__(self, tenant: TenantBotConfig) -> None:
        intents = discord.Intents.none()
        intents.guilds = True
        intents.guild_messages = True
        intents.dm_messages = True
        intents.message_content = True
        intents.members = True
        super().__init__(intents=intents)
        self.tenant = tenant

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
        logger.info(
            "[discord-gateway] RESUMED tenant=%s tenant_id=%d",
            self.tenant.tenant_code,
            self.tenant.tenant_id,
        )

    async def on_disconnect(self) -> None:
        logger.warning(
            "[discord-gateway] DISCONNECT tenant=%s tenant_id=%d",
            self.tenant.tenant_code,
            self.tenant.tenant_id,
        )


async def run_gateway(tenant: TenantBotConfig) -> None:
    """1 テナント分の Gateway 接続を維持する。切断時は discord.py が自動再接続する。

    LoginFailure は致命的（Token 不正/失効）として例外を re-raise する。
    main 側で全テナント致命時に非ゼロ終了する。

    一般例外は指数バックオフで再起動（最大 60 秒）。
    """
    backoff = 5
    max_backoff = 60
    while True:
        client = JarvisDiscordClient(tenant)
        try:
            await client.start(tenant.bot_token, reconnect=True)
        except discord.LoginFailure:
            logger.critical(
                "[discord-gateway] LoginFailure tenant=%s — Token 不正/失効。"
                "Discord Developer Portal で Token を再発行し Bitwarden を更新すること",
                tenant.tenant_code,
            )
            raise
        except asyncio.CancelledError:
            logger.info("[discord-gateway] CancelledError tenant=%s", tenant.tenant_code)
            await client.close()
            raise
        except Exception as exc:
            logger.exception(
                "[discord-gateway] 例外発生 tenant=%s exc_type=%s, %d 秒後に再起動",
                tenant.tenant_code,
                type(exc).__name__,
                backoff,
            )
            try:
                await client.close()
            except Exception:
                pass
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, max_backoff)
        else:
            backoff = 5
