#!/usr/bin/env python3
"""API解析.csv (横展開、仕入元 × 商品問い合わせのマトリクス) を pivot して
public.discord_inbound_messages に seed する (spec.md v1.3 / F5 連携)。

入力: astro-webapp/sheets/raw/API解析.csv (4880 行 × 46 列)
出力: public.discord_inbound_messages に INSERT (discord_message_id ON CONFLICT)

CSV 構造:
  L1: 仕入元, <仕入元名1>, <仕入元名2>, ..., <仕入元名45>
  L2: タイムスタンプ, ...
  L3+: 「①[メッセージ原文]...」のような問い合わせ行 + 各列に仕入元の回答

Pivot ロジック:
  各 (row >= 3, col >= 2) のセルが空でなければ:
    supplier_name = L1 の col 位置
    raw_content   = そのセルの値
    discord_channel_id = "CSV_IMPORT_{supplier_id:03d}" (fake、後で実 channel 接続時に更新)
    discord_message_id = "CSV_{seq:06d}" (fake、連番)
    received_at   = NOW()
    parse_status  = 'pending'

注意: discord_channel_id / discord_message_id は本物の Discord ID ではない。
テストデータとして F3/F4 解析パイプライン動作確認用。
後の実 Discord 受信時は実 ID で別レコード。

実行方法:
  docker compose exec -w /app backend python scripts/seed_discord_inbound_from_api_analysis.py --dry-run
  docker compose exec -w /app backend python scripts/seed_discord_inbound_from_api_analysis.py --apply

冪等: ON CONFLICT (discord_message_id) DO NOTHING (再走時の重複防止)

前提:
  - seed_suppliers_from_line_master.py 実行済 (supplier_name で resolve 可能)
"""
from __future__ import annotations

import argparse
import asyncio
import csv
import logging
import os
import sys
from pathlib import Path
from typing import Iterable, NamedTuple

_APP_ROOT = Path(__file__).resolve().parent.parent
if str(_APP_ROOT) not in sys.path:
    sys.path.insert(0, str(_APP_ROOT))

from sqlalchemy import text  # noqa: E402
from sqlalchemy.ext.asyncio import create_async_engine  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent.parent
CSV_CANDIDATES = [
    BASE_DIR / "sheets" / "discord_inbound_raw.csv",
    BASE_DIR / "sheets" / "raw" / "API解析.csv",
]


class MessageRow(NamedTuple):
    supplier_name: str
    raw_content: str


def _load_rows() -> list[MessageRow]:
    csv_path = next((p for p in CSV_CANDIDATES if p.exists()), None)
    if csv_path is None:
        logger.error("CSV ファイルが見つかりません。候補: %s", CSV_CANDIDATES)
        sys.exit(1)
    logger.info("CSV 検出: %s", csv_path)

    with csv_path.open(encoding="utf-8") as f:
        all_rows = list(csv.reader(f))

    if not all_rows:
        logger.error("CSV が空")
        sys.exit(1)

    # L1: ヘッダー (仕入元名)
    header = [h.strip() for h in all_rows[0]]
    if not header or header[0] != "仕入元":
        logger.error("L1 ヘッダーが想定外: %r", header[:5])
        sys.exit(1)
    supplier_columns = header[1:]  # index 0 はラベル列

    messages: list[MessageRow] = []
    # L2 (タイムスタンプ) は skip
    # L3 以降を pivot
    for row_idx in range(2, len(all_rows)):
        row = all_rows[row_idx]
        for col_idx in range(1, min(len(row), len(supplier_columns) + 1)):
            cell = (row[col_idx] or "").strip()
            if not cell:
                continue
            supplier_name = supplier_columns[col_idx - 1].strip()
            if not supplier_name:
                continue
            messages.append(MessageRow(supplier_name, cell))

    return messages


async def _seed(rows: Iterable[MessageRow], dry_run: bool) -> None:
    rows_list = list(rows)

    url = os.getenv("DATABASE_URL")
    if not url:
        logger.error("DATABASE_URL not set")
        sys.exit(1)
    if url.startswith("postgresql://"):
        url = "postgresql+asyncpg://" + url[len("postgresql://"):]
    engine = create_async_engine(url, echo=False)

    try:
        async with engine.begin() as conn:
            # supplier_name → supplier_id lookup
            sup_rows = (await conn.execute(text("SELECT id, name FROM public.suppliers"))).all()
            sup_map = {r.name: r.id for r in sup_rows}
            logger.info("supplier lookup: %d entries loaded", len(sup_map))

            resolved = []
            unresolved = 0
            for r in rows_list:
                sid = sup_map.get(r.supplier_name)
                if sid is None:
                    unresolved += 1
                    continue
                resolved.append((r, sid))
            if unresolved > 0:
                logger.warning("supplier 未登録で skip した行: %d", unresolved)
            logger.info("resolve 成功: %d / %d", len(resolved), len(rows_list))

            if dry_run:
                logger.info("dry-run: %d 行を投入予定 (DB 変更なし)", len(resolved))
                for (r, sid) in resolved[:3]:
                    preview = r.raw_content[:80].replace("\n", " ")
                    logger.info("  sample: supplier=%s(id=%d) raw=%r", r.supplier_name, sid, preview)
                if len(resolved) > 3:
                    logger.info("  ... (残り %d 行は省略)", len(resolved) - 3)
                return

            before = (await conn.execute(text(
                "SELECT COUNT(*) FROM public.discord_inbound_messages WHERE discord_channel_id LIKE 'CSV_IMPORT_%'"
            ))).scalar_one()
            logger.info("適用前 (CSV_IMPORT のみ) public.discord_inbound_messages 件数: %d", before)

            inserted = skipped = 0
            for seq, (r, sid) in enumerate(resolved, start=1):
                channel_id = f"CSV_IMPORT_{sid:03d}"
                message_id = f"CSV_{seq:06d}"
                result = await conn.execute(
                    text(
                        """
                        INSERT INTO public.discord_inbound_messages
                            (supplier_id, discord_channel_id, discord_message_id, raw_content, parse_status)
                        VALUES (:sid, :ch, :mid, :raw, 'pending')
                        ON CONFLICT (discord_message_id) DO NOTHING
                        RETURNING id
                        """
                    ),
                    {"sid": sid, "ch": channel_id, "mid": message_id, "raw": r.raw_content},
                )
                if result.fetchone() is not None:
                    inserted += 1
                else:
                    skipped += 1

            after = (await conn.execute(text(
                "SELECT COUNT(*) FROM public.discord_inbound_messages WHERE discord_channel_id LIKE 'CSV_IMPORT_%'"
            ))).scalar_one()
            logger.info("適用後 (CSV_IMPORT のみ) 件数: %d (inserted=%d, skipped=%d)",
                        after, inserted, skipped)
    finally:
        await engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description="API解析.csv pivot → public.discord_inbound_messages seed")
    g = parser.add_mutually_exclusive_group(required=True)
    g.add_argument("--dry-run", action="store_true")
    g.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    rows = _load_rows()
    asyncio.run(_seed(rows, dry_run=args.dry_run))


if __name__ == "__main__":
    main()
