#!/usr/bin/env python3
"""
SSE Pub/Sub 正常性確認スクリプト（ADR-025: 3点セットの「検証」部分）。

使用方法:
    docker compose exec backend python /app/scripts/verify_sse_health.py

終了コード: 0=正常、1=異常
"""
from __future__ import annotations

import asyncio
import os
import sys


async def main() -> None:
    import redis.asyncio as aioredis

    base = os.getenv("REDIS_URL", "redis://redis:6379/0")
    url = base.rsplit("/", 1)[0] + "/3"
    print(f"[1/3] Redis DB3 接続確認: {url}")
    r = aioredis.from_url(url, decode_responses=True)
    try:
        await r.ping()
        print("  OK: ping 成功")
    except Exception as e:
        print(f"  NG: {e}")
        sys.exit(1)

    print("[2/3] publish/subscribe 疎通確認")
    received = asyncio.Event()

    async def sub() -> None:
        ps = r.pubsub()
        await ps.subscribe("inbox:__verify__")
        async for msg in ps.listen():
            if msg["type"] == "message":
                received.set()
                await ps.aclose()
                return

    t = asyncio.create_task(sub())
    await asyncio.sleep(0.1)
    await r.publish("inbox:__verify__", "update")
    try:
        await asyncio.wait_for(received.wait(), timeout=5.0)
        print("  OK: pub/sub 疎通確認成功")
    except asyncio.TimeoutError:
        print("  NG: 5秒タイムアウト")
        sys.exit(1)
    finally:
        t.cancel()

    print("[3/3] 接続数カウンター確認")
    from app.services.sse_pubsub import decrement_connection, increment_connection

    assert await increment_connection(0), "increment 失敗"
    await decrement_connection(0)
    print("  OK: カウンター正常")

    await r.aclose()
    print("\n全チェック通過 ✓")


if __name__ == "__main__":
    asyncio.run(main())
