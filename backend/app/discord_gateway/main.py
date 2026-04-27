import asyncio
import logging
import signal
import sys

from app.discord_gateway.client import run_gateway
from app.discord_gateway.config import get_log_level, load_tenant_bot_configs


def _setup_logging() -> None:
    logging.basicConfig(
        level=get_log_level(),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )


async def _main_async() -> int:
    tenants = load_tenant_bot_configs()
    if not tenants:
        logging.warning(
            "[discord-gateway] DISCORD_BOT_TOKEN_<TENANT_ID> が未設定のため idle で待機します"
        )
        stop_event = asyncio.Event()

        def _stop(*_: object) -> None:
            stop_event.set()

        loop = asyncio.get_running_loop()
        for sig in (signal.SIGTERM, signal.SIGINT):
            loop.add_signal_handler(sig, _stop)
        await stop_event.wait()
        return 0

    logging.info(
        "[discord-gateway] 起動 tenants=%s",
        ",".join(f"{t.tenant_code}({t.tenant_id})" for t in tenants),
    )

    tasks = [asyncio.create_task(run_gateway(t), name=f"gw-{t.tenant_code}") for t in tenants]
    try:
        await asyncio.gather(*tasks)
    except asyncio.CancelledError:
        for t in tasks:
            t.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        raise
    return 0


def main() -> int:
    _setup_logging()
    try:
        return asyncio.run(_main_async())
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    sys.exit(main())
