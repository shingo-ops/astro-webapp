import asyncio
import logging
import os
import signal
import sys

from app.discord_gateway.client import run_gateway
from app.discord_gateway.config import get_log_level, load_tenant_bot_configs

logger = logging.getLogger(__name__)


def _fatal_cooldown_seconds() -> int:
    """致命的エラーで非ゼロ終了する前のクールダウン秒数（既定 60s）。

    Docker `restart: unless-stopped` は exit のたびにコンテナを再起動する。
    Token 失効等で起動直後に毎回 fatal になると、再起動→Discord 再接続が高頻度で
    繰り返され、短時間に大量接続 → Discord による Bot Token 自動リセットを招く
    （2026-06-02 実発生）。終了前にクールダウンを挟み再起動頻度を抑える。
    """
    try:
        return max(0, int(os.getenv("DISCORD_GATEWAY_FATAL_COOLDOWN", "60")))
    except ValueError:
        return 60


def _setup_logging() -> None:
    logging.basicConfig(
        level=get_log_level(),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )


def _install_signal_handlers(stop_event: asyncio.Event) -> None:
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, stop_event.set)


async def _run_with_shutdown(tenants: list) -> int:
    stop_event = asyncio.Event()
    _install_signal_handlers(stop_event)

    if not tenants:
        logger.warning(
            "[discord-gateway] DISCORD_BOT_TOKEN_<TENANT_ID> が未設定のため idle で待機します"
        )
        await stop_event.wait()
        return 0

    logger.info(
        "[discord-gateway] 起動 tenants=%s",
        ",".join(f"{t.tenant_code}({t.tenant_id})" for t in tenants),
    )

    tasks = [
        asyncio.create_task(run_gateway(t), name=f"gw-{t.tenant_code}")
        for t in tenants
    ]
    gather_task = asyncio.gather(*tasks, return_exceptions=True)
    stop_task = asyncio.create_task(stop_event.wait(), name="gw-shutdown-wait")

    try:
        done, _ = await asyncio.wait(
            [gather_task, stop_task],
            return_when=asyncio.FIRST_COMPLETED,
        )
        if stop_task in done:
            logger.info("[discord-gateway] SIGTERM 受信、graceful shutdown 開始")
            for t in tasks:
                t.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
        else:
            stop_task.cancel()

        results = await gather_task
    except asyncio.CancelledError:
        for t in tasks:
            t.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        raise

    fatal = [r for r in results if isinstance(r, Exception) and not isinstance(r, asyncio.CancelledError)]
    if fatal and len(fatal) == len(tenants):
        cooldown = _fatal_cooldown_seconds()
        logger.critical(
            "[discord-gateway] 全 %d テナントで致命的エラー、%d 秒クールダウン後に非ゼロ終了します"
            "（Docker 再起動の連打による Discord 再接続storm→token reset を防ぐ）",
            len(fatal),
            cooldown,
        )
        if cooldown > 0:
            # SIGTERM（デプロイ停止）が来たら即座に終了できるよう中断可能な待機にする。
            try:
                await asyncio.wait_for(stop_event.wait(), timeout=cooldown)
            except asyncio.TimeoutError:
                pass
        return 1
    return 0


async def _main_async() -> int:
    tenants = load_tenant_bot_configs()
    return await _run_with_shutdown(tenants)


def main() -> int:
    _setup_logging()
    try:
        return asyncio.run(_main_async())
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    sys.exit(main())
