#!/usr/bin/env python3
"""
Phase 1 再設計 / 顧客マスタ原本CSV → customers 系テーブルへの投入スクリプト。

入力: sheets/customers_master.csv（43列）
出力: {schema}.customers + customer_addresses + customer_sales_channels + customer_discord

投入順序:
    本スクリプトの前に migrate_staff_from_sheet.py を実行しておくこと。
    sales_rep_id の引き当てに staff テーブルが必要。

設計方針:
    - 営業担当者 列の値（氏名 or 苗字）から sales_rep_id を引き当て
    - lead_id は NULL で投入（leads 側の移行は別スプリントで）
    - billing/delivery どちらかが空ならその行は作らない
    - 販売先カンマ区切り → customer_sales_channels N行
    - Discord関連フィールドに値があれば customer_discord 1行、なければ作らない
    - CT-00030 / CT-00032 等の重複候補は status='pending_dedup_review' で先行投入
    - 月間売上見込額は 'manual' source で投入（既存顧客のAI再分析は Phase 3 以降）
    - 列名タイポ「Discrod / Shippment」は本スクリプト内で吸収

実行方法（VPS側 Docker コンテナ内）:
    docker compose exec backend python /app/scripts/data_migration/migrate_customers_from_sheet.py

環境変数:
    DATABASE_URL: 接続先 (必須)
    TENANT_CODE: 対象テナントコード (デフォルト: 'test-corp')
    SHEETS_DIR: CSV 配置ディレクトリ (デフォルト: /app/sheets)

変更履歴:
    2026-04-23: 初版作成
"""
from __future__ import annotations

import asyncio
import csv
import logging
import os
import re
import sys
from datetime import datetime
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

sys.path.insert(0, str(Path(__file__).resolve().parent))
from data_cleansing import (  # noqa: E402
    parse_amount,
    parse_bool_loose,
    parse_contact_channel,
    parse_country_code,
    parse_integer,
    parse_phone_e164,
    split_sales_channels,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    logger.error("DATABASE_URL 環境変数が設定されていません")
    sys.exit(1)

TENANT_CODE = os.getenv("TENANT_CODE", "test-corp")
SHEETS_DIR = Path(os.getenv("SHEETS_DIR", "/app/sheets"))
CUSTOMERS_CSV = SHEETS_DIR / "customers_master.csv"

CUSTOMER_CODE_PATTERN = re.compile(r"^CT-\d+$")

# 2026-04-23 時点で判明している重複候補（暫定: status='pending_dedup_review' タグで両方投入）
KNOWN_DUP_CANDIDATES = {"CT-00030", "CT-00032"}


async def get_tenant_info(engine, tenant_code: str) -> tuple[int, str]:
    async with engine.connect() as conn:
        result = await conn.execute(
            text("SELECT id FROM public.tenants WHERE tenant_code = :code AND is_active = true"),
            {"code": tenant_code},
        )
        row = result.first()
        if not row:
            raise RuntimeError(f"テナント '{tenant_code}' が見つからないか無効です")
        return row.id, f"tenant_{row.id:03d}"


def load_customer_rows(csv_path: Path) -> list[dict[str, str]]:
    with csv_path.open(encoding="utf-8") as f:
        reader = csv.DictReader(f)
        rows = list(reader)
    valid_rows = [
        r for r in rows
        if (r.get("顧客ID") or "").strip() and CUSTOMER_CODE_PATTERN.match((r.get("顧客ID") or "").strip())
    ]
    logger.info("CSV 読込: 全%d行中、有効な顧客 %d行を抽出", len(rows), len(valid_rows))
    return valid_rows


def parse_registered_at(value: str | None) -> datetime | None:
    """
    登録日時文字列を datetime に変換。スプレッドシートの形式揺れを吸収。

    対応形式:
      - 日本 ISO: 2025-10-06 12:34:56 / 2025/10/06 12:34:56 / 2025-10-06 / 2025/10/06
      - 米国順: 11/6/2025 17:16:16 / 11/06/2025 / 11/6/25 等（米国顧客の
        Googleスプレッドシート書式）
    変換不能は None + warn ログ。
    """
    if not value:
        return None
    stripped = value.strip()
    if not stripped:
        return None
    formats = (
        "%Y-%m-%d %H:%M:%S",
        "%Y/%m/%d %H:%M:%S",
        "%Y-%m-%d",
        "%Y/%m/%d",
        # 米国順（MDY）: 11/6/2025 17:16:16 など
        "%m/%d/%Y %H:%M:%S",
        "%m/%d/%Y %H:%M",
        "%m/%d/%Y",
        "%m/%d/%y %H:%M:%S",
        "%m/%d/%y",
    )
    for fmt in formats:
        try:
            return datetime.strptime(stripped, fmt)
        except ValueError:
            continue
    logger.warning("parse_registered_at: 変換不能 %r", value)
    return None


async def resolve_sales_rep_id(conn, schema: str, tenant_id: int, rep_name: str) -> int | None:
    """営業担当者列の値から staff.id を引き当て。氏名 or 苗字で照合。"""
    cleaned = (rep_name or "").strip()
    if not cleaned:
        return None
    result = await conn.execute(
        text(f"""
            SELECT id FROM {schema}.staff
            WHERE tenant_id = :tid
              AND (
                surname_jp = :name
                OR CONCAT(surname_jp, ' ', given_name_jp) = :name
                OR CONCAT(surname_jp, given_name_jp) = :name
              )
            LIMIT 1
        """),
        {"tid": tenant_id, "name": cleaned},
    )
    row = result.first()
    if row is None:
        logger.warning("sales_rep 解決不能: '%s' → NULL", cleaned)
    return row.id if row else None


def has_any_value(row: dict[str, str], keys: list[str]) -> bool:
    """指定キー群のうち1つでも空でない値があれば True。"""
    return any((row.get(k) or "").strip() for k in keys)


BILLING_KEYS = ["B Name", "B Email", "B Telephone", "B Tax ID", "B Address 1", "B Address 2", "B City", "B State", "B Zip", "B Country"]
DELIVERY_KEYS = ["D Name", "D Telephone", "D Email", "D Tax ID", "D Address 1", "D Address 2", "D Address 3", "D City", "D State", "D Zip", "D Country"]
DISCORD_KEYS = ["Discord参加", "Discord チャンネルID", "Discord ユーザーID", "Discrod 請求書 webhook", "Discrod 発送通知 webhook", "Shippment webhook"]


async def insert_customer_with_related(
    conn, schema: str, tenant_id: int, row: dict[str, str]
) -> int:
    """customers + 副テーブル群を投入。"""
    customer_code = (row.get("顧客ID") or "").strip()
    company_name = (row.get("B Name") or row.get("D Name") or "").strip() or None

    billing_display_name = (row.get("B Name") or "").strip() or None
    payment_recipient_raw = (row.get("支払い名義") or "").strip()
    # B Name と同一なら NULL（冗長を避ける）
    payment_recipient_name = (
        payment_recipient_raw
        if payment_recipient_raw and payment_recipient_raw != billing_display_name
        else None
    )

    per_order_amount = parse_amount(row.get("1回発注額"))
    monthly_frequency = parse_integer(row.get("月間頻度"))
    monthly_forecast = parse_amount(row.get("月間売上見込額"))

    rep_id = await resolve_sales_rep_id(conn, schema, tenant_id, row.get("営業担当者") or "")

    status = "pending_dedup_review" if customer_code in KNOWN_DUP_CANDIDATES else "active"
    registered_at = parse_registered_at(row.get("登録日時"))

    # monthly_forecast の連動は Python 側で決定（asyncpg の AmbiguousParameterError 回避）
    forecast_source = "manual" if monthly_forecast is not None else None
    forecast_updated_at_will_be_set = monthly_forecast is not None

    result = await conn.execute(
        text(f"""
            INSERT INTO {schema}.customers (
                tenant_id, customer_code, lead_id, sales_rep_id, company_name,
                trust_level, priority_focus,
                per_order_amount, monthly_frequency,
                monthly_forecast, monthly_forecast_source, monthly_forecast_updated_at,
                meeting_requested,
                billing_display_name, payment_recipient_name,
                fedex_account, shipping_note, primary_contact_channel, status,
                created_at
            ) VALUES (
                :tenant_id, :customer_code, NULL, :sales_rep_id, :company_name,
                :trust_level, :priority_focus,
                :per_order_amount, :monthly_frequency,
                :monthly_forecast, :monthly_forecast_source, :monthly_forecast_updated_at,
                :meeting_requested,
                :billing_display_name, :payment_recipient_name,
                :fedex_account, :shipping_note, :primary_contact_channel, :status,
                COALESCE(:created_at, NOW())
            )
            ON CONFLICT (tenant_id, customer_code) DO UPDATE SET
                sales_rep_id = EXCLUDED.sales_rep_id,
                company_name = EXCLUDED.company_name,
                trust_level = EXCLUDED.trust_level,
                priority_focus = EXCLUDED.priority_focus,
                per_order_amount = EXCLUDED.per_order_amount,
                monthly_frequency = EXCLUDED.monthly_frequency,
                monthly_forecast = EXCLUDED.monthly_forecast,
                monthly_forecast_source = EXCLUDED.monthly_forecast_source,
                monthly_forecast_updated_at = EXCLUDED.monthly_forecast_updated_at,
                meeting_requested = EXCLUDED.meeting_requested,
                billing_display_name = EXCLUDED.billing_display_name,
                payment_recipient_name = EXCLUDED.payment_recipient_name,
                fedex_account = EXCLUDED.fedex_account,
                shipping_note = EXCLUDED.shipping_note,
                primary_contact_channel = EXCLUDED.primary_contact_channel,
                status = EXCLUDED.status,
                updated_at = NOW()
            RETURNING id
        """),
        {
            "tenant_id": tenant_id,
            "customer_code": customer_code,
            "sales_rep_id": rep_id,
            "company_name": company_name,
            "trust_level": parse_integer(row.get("信頼度")),
            "priority_focus": (row.get("重視ポイント") or "").strip() or None,
            "per_order_amount": per_order_amount,
            "monthly_frequency": monthly_frequency,
            "monthly_forecast": monthly_forecast,
            "monthly_forecast_source": forecast_source,
            # updated_at は INSERT 時は NULL、値あり時のみ後続 UPDATE で NOW() 設定
            "monthly_forecast_updated_at": None,
            "meeting_requested": parse_bool_loose(row.get("面談希望")),
            "billing_display_name": billing_display_name,
            "payment_recipient_name": payment_recipient_name,
            "fedex_account": (row.get("FedEx ID") or "").strip() or None,
            "shipping_note": (row.get("発送時メモ") or "").strip() or None,
            "primary_contact_channel": parse_contact_channel(row.get("連絡ツール")),
            "status": status,
            "created_at": registered_at,
        },
    )
    customer_id = result.scalar_one()

    # monthly_forecast が値ありなら updated_at を NOW() に（bind 不能のため別クエリ）
    if forecast_updated_at_will_be_set:
        await conn.execute(
            text(f"UPDATE {schema}.customers SET monthly_forecast_updated_at = NOW() WHERE id = :cid"),
            {"cid": customer_id},
        )

    # 住所は UNIQUE 制約が無く（将来の複数配送先対応のため）、
    # かつスクリプトの再実行で二重化するのを防ぐため、
    # billing/delivery の insert 前に既存の住所行を削除する。
    # 将来的にアプリ側で追加された住所も対象になるが、本スクリプトは
    # 原本CSVからの冪等再投入専用なのでこの挙動で問題ない。
    await conn.execute(
        text(f"DELETE FROM {schema}.customer_addresses WHERE customer_id = :cid"),
        {"cid": customer_id},
    )

    # billing address
    if has_any_value(row, BILLING_KEYS):
        await conn.execute(
            text(f"""
                INSERT INTO {schema}.customer_addresses (
                    customer_id, address_type, name, email, telephone, tax_id,
                    address_line_1, address_line_2, city, state, zip, country_code
                ) VALUES (
                    :cid, 'billing', :name, :email, :telephone, :tax_id,
                    :addr1, :addr2, :city, :state, :zip, :country
                )
            """),
            {
                "cid": customer_id,
                "name": (row.get("B Name") or "").strip() or None,
                "email": (row.get("B Email") or "").strip() or None,
                "telephone": parse_phone_e164(row.get("B Telephone")),
                "tax_id": (row.get("B Tax ID") or "").strip() or None,
                "addr1": (row.get("B Address 1") or "").strip() or None,
                "addr2": (row.get("B Address 2") or "").strip() or None,
                "city": (row.get("B City") or "").strip() or None,
                "state": (row.get("B State") or "").strip() or None,
                "zip": (row.get("B Zip") or "").strip() or None,
                "country": parse_country_code(row.get("B Country")),
            },
        )

    # delivery address
    if has_any_value(row, DELIVERY_KEYS):
        await conn.execute(
            text(f"""
                INSERT INTO {schema}.customer_addresses (
                    customer_id, address_type, name, email, telephone, tax_id,
                    address_line_1, address_line_2, address_line_3, city, state, zip, country_code
                ) VALUES (
                    :cid, 'delivery', :name, :email, :telephone, :tax_id,
                    :addr1, :addr2, :addr3, :city, :state, :zip, :country
                )
            """),
            {
                "cid": customer_id,
                "name": (row.get("D Name") or "").strip() or None,
                "email": (row.get("D Email") or "").strip() or None,
                "telephone": parse_phone_e164(row.get("D Telephone")),
                "tax_id": (row.get("D Tax ID") or "").strip() or None,
                "addr1": (row.get("D Address 1") or "").strip() or None,
                "addr2": (row.get("D Address 2") or "").strip() or None,
                "addr3": (row.get("D Address 3") or "").strip() or None,
                "city": (row.get("D City") or "").strip() or None,
                "state": (row.get("D State") or "").strip() or None,
                "zip": (row.get("D Zip") or "").strip() or None,
                "country": parse_country_code(row.get("D Country")),
            },
        )

    # sales channels
    for channel in split_sales_channels(row.get("販売先")):
        await conn.execute(
            text(f"""
                INSERT INTO {schema}.customer_sales_channels (customer_id, channel)
                VALUES (:cid, :channel)
                ON CONFLICT (customer_id, channel) DO NOTHING
            """),
            {"cid": customer_id, "channel": channel},
        )

    # Discord
    if has_any_value(row, DISCORD_KEYS):
        # shipment_webhook: 「Discrod 発送通知 webhook」を優先、無ければ「Shippment webhook」
        shipment_webhook = (
            (row.get("Discrod 発送通知 webhook") or "").strip()
            or (row.get("Shippment webhook") or "").strip()
            or None
        )
        await conn.execute(
            text(f"""
                INSERT INTO {schema}.customer_discord (
                    customer_id, is_joined, channel_id, user_id,
                    invoice_webhook, shipment_webhook
                ) VALUES (
                    :cid, :is_joined, :channel_id, :user_id, :invoice_webhook, :shipment_webhook
                )
                ON CONFLICT (customer_id) DO UPDATE SET
                    is_joined = EXCLUDED.is_joined,
                    channel_id = EXCLUDED.channel_id,
                    user_id = EXCLUDED.user_id,
                    invoice_webhook = EXCLUDED.invoice_webhook,
                    shipment_webhook = EXCLUDED.shipment_webhook,
                    updated_at = NOW()
            """),
            {
                "cid": customer_id,
                "is_joined": parse_bool_loose(row.get("Discord参加")),
                "channel_id": (row.get("Discord チャンネルID") or "").strip() or None,
                "user_id": (row.get("Discord ユーザーID") or "").strip() or None,
                "invoice_webhook": (row.get("Discrod 請求書 webhook") or "").strip() or None,
                "shipment_webhook": shipment_webhook,
            },
        )

    logger.info("  ✓ %s 投入 (company='%s', status=%s)", customer_code, company_name, status)
    return customer_id


async def main() -> None:
    logger.info("=" * 72)
    logger.info("顧客マスタ移行開始: tenant_code=%s, csv=%s", TENANT_CODE, CUSTOMERS_CSV)
    logger.info("=" * 72)

    if not CUSTOMERS_CSV.exists():
        logger.error("CSV が見つかりません: %s", CUSTOMERS_CSV)
        sys.exit(1)

    engine = create_async_engine(DATABASE_URL, echo=False)
    try:
        tenant_id, schema = await get_tenant_info(engine, TENANT_CODE)
        logger.info("対象テナント: id=%d, schema=%s", tenant_id, schema)

        rows = load_customer_rows(CUSTOMERS_CSV)
        inserted = 0
        async with engine.begin() as conn:
            await conn.execute(text(f"SET search_path = {schema}, public"))
            await conn.execute(text(f"SET app.tenant_id = '{tenant_id}'"))

            for row in rows:
                await insert_customer_with_related(conn, schema, tenant_id, row)
                inserted += 1

        logger.info("=" * 72)
        logger.info("✓ 顧客マスタ移行完了: 投入 %d件", inserted)
        logger.info("=" * 72)
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
