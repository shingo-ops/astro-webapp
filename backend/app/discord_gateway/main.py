import asyncio
import logging
import signal
import sys

from app.discord_gateway.client import run_gateway
from app.discord_gateway.config import get_log_level, load_tenant_bot_configs

logger = logging.getLogger(__name__)


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
        logger.critical(
            "[discord-gateway] 全 %d テナントで致命的エラー、非ゼロ終了します",
            len(fatal),
        )
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
