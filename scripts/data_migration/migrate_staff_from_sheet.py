#!/usr/bin/env python3
"""
Phase 1 再設計 / 担当者マスタ原本CSV → staff 系テーブルへの投入スクリプト。

入力: sheets/staff_master.csv（20列）
出力: {schema}.staff + {schema}.staff_emails + {schema}.staff_ui_preferences

設計方針:
    - public.users の作成は本スクリプトでは行わない（Firebase 初回ログイン時にアプリが解決）
    - staff.user_id と staff.firebase_uid は NULL で投入、後で認証フローから埋める
    - EMP-00005 のような複数行（同じ staff_code）は primary_email=最終行、
      他の行のメールは staff_emails に purpose='secondary' で追加
    - EMP-00002「営業 太郎」等のテストデータはスキップ
    - CSV 末尾の空行や「FBトークン」等のメモ行は自動スキップ（staff_code が EMP-* パターンに一致しない）

実行方法（VPS側 Docker コンテナ内）:
    docker compose exec backend python /app/scripts/data_migration/migrate_staff_from_sheet.py
    docker compose exec -e TENANT_CODE=test-corp backend python /app/scripts/data_migration/migrate_staff_from_sheet.py

環境変数:
    DATABASE_URL: 接続先 (必須)
    TENANT_CODE: 対象テナントコード (デフォルト: 'test-corp' = tenant_001 想定)
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
from collections import defaultdict
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

sys.path.insert(0, str(Path(__file__).resolve().parent))
from data_cleansing import (  # noqa: E402
    is_test_user_name,
    normalize_status,
    parse_bool_loose,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    logger.error("DATABASE_URL 環境変数が設定されていません")
    sys.exit(1)

TENANT_CODE = os.getenv("TENANT_CODE", "test-corp")
SHEETS_DIR = Path(os.getenv("SHEETS_DIR", "/app/sheets"))
STAFF_CSV = SHEETS_DIR / "staff_master.csv"

# 有効な staff_code パターン（EMP-NNNNN 形式のみ受け付ける）
STAFF_CODE_PATTERN = re.compile(r"^EMP-\d+$")


async def get_tenant_info(engine, tenant_code: str) -> tuple[int, str]:
    """tenant_code から (tenant_id, schema_name) を解決する。"""
    async with engine.connect() as conn:
        result = await conn.execute(
            text("SELECT id FROM public.tenants WHERE tenant_code = :code AND is_active = true"),
            {"code": tenant_code},
        )
        row = result.first()
        if not row:
            raise RuntimeError(f"テナント '{tenant_code}' が見つからないか無効です")
        return row.id, f"tenant_{row.id:03d}"


def load_staff_rows(csv_path: Path) -> list[dict[str, str]]:
    """
    CSV を読み込み、有効な staff 行（staff_code が EMP-NNNNN 形式）のみ返す。
    空行・「FBトークン」等のメモ行は除外。
    """
    with csv_path.open(encoding="utf-8") as f:
        reader = csv.DictReader(f)
        rows = list(reader)
    valid_rows = [
        r for r in rows
        if (r.get("担当者ID") or "").strip() and STAFF_CODE_PATTERN.match((r.get("担当者ID") or "").strip())
    ]
    logger.info("CSV 読込: 全%d行中、有効 staff %d行を抽出", len(rows), len(valid_rows))
    return valid_rows


def group_by_staff_code(rows: list[dict[str, str]]) -> dict[str, list[dict[str, str]]]:
    """staff_code 単位でグルーピング（EMP-00005 の複数行を束ねる）。"""
    groups: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in rows:
        staff_code = (row.get("担当者ID") or "").strip()
        groups[staff_code].append(row)
    return dict(groups)


async def resolve_role_id(conn, schema: str, tenant_id: int, role_name: str) -> int | None:
    """役割名から role_id を解決。"""
    result = await conn.execute(
        text(f"SELECT id FROM {schema}.roles WHERE tenant_id = :tid AND name = :name"),
        {"tid": tenant_id, "name": role_name},
    )
    row = result.first()
    return row.id if row else None


async def insert_staff_with_related(
    conn, schema: str, tenant_id: int, staff_code: str, rows: list[dict[str, str]]
) -> int | None:
    """
    staff 本体 + staff_emails + staff_ui_preferences をまとめて投入する。
    同じ staff_code で複数行がある場合:
      - 最終行（rows[-1]）を primary_email ソースとして使用
      - 他の行のメールを staff_emails.email に purpose='secondary' で追加
    戻り値: 投入された staff.id、スキップ時は None
    """
    main_row = rows[-1]

    surname_jp = (main_row.get("苗字（日本語）") or "").strip()
    given_name_jp = (main_row.get("名前（日本語）") or "").strip()

    # テストデータ判定（EMP-00002 太郎 等はスキップ）
    if is_test_user_name(surname_jp, given_name_jp):
        logger.info("  %s スキップ（テストデータ判定: '%s %s')", staff_code, surname_jp, given_name_jp)
        return None

    role_name = (main_row.get("役割") or "").strip()
    role_id = await resolve_role_id(conn, schema, tenant_id, role_name)
    if role_id is None:
        logger.warning("  %s スキップ（役割 '%s' が未解決）", staff_code, role_name)
        return None

    primary_email = (main_row.get("メール") or "").strip()
    if not primary_email:
        logger.warning("  %s スキップ（primary_email 空）", staff_code)
        return None

    status = normalize_status(main_row.get("ステータス"))

    insert_result = await conn.execute(
        text(f"""
            INSERT INTO {schema}.staff (
                tenant_id, staff_code, surname_jp, given_name_jp,
                surname_kana, given_name_kana, surname_en, given_name_en,
                primary_email, discord_user_id, role_id, status,
                user_id, firebase_uid
            ) VALUES (
                :tenant_id, :staff_code, :surname_jp, :given_name_jp,
                :surname_kana, :given_name_kana, :surname_en, :given_name_en,
                :primary_email, :discord_user_id, :role_id, :status,
                NULL, NULL
            )
            ON CONFLICT (tenant_id, staff_code) DO UPDATE SET
                surname_jp = EXCLUDED.surname_jp,
                given_name_jp = EXCLUDED.given_name_jp,
                surname_kana = EXCLUDED.surname_kana,
                given_name_kana = EXCLUDED.given_name_kana,
                surname_en = EXCLUDED.surname_en,
                given_name_en = EXCLUDED.given_name_en,
                primary_email = EXCLUDED.primary_email,
                discord_user_id = EXCLUDED.discord_user_id,
                role_id = EXCLUDED.role_id,
                status = EXCLUDED.status,
                updated_at = NOW()
            RETURNING id
        """),
        {
            "tenant_id": tenant_id,
            "staff_code": staff_code,
            "surname_jp": surname_jp,
            "given_name_jp": given_name_jp,
            "surname_kana": (main_row.get("苗字ふりがな") or "").strip() or None,
            "given_name_kana": (main_row.get("名前ふりがな") or "").strip() or None,
            "surname_en": (main_row.get("苗字（英語）") or "").strip() or None,
            "given_name_en": (main_row.get("名前（英語）") or "").strip() or None,
            "primary_email": primary_email,
            "discord_user_id": (main_row.get("Discord ID") or "").strip() or None,
            "role_id": role_id,
            "status": status,
        },
    )
    staff_id = insert_result.scalar_one()

    # 追加メール（主より前の行のメール）を staff_emails へ
    secondary_emails = {
        (r.get("メール") or "").strip()
        for r in rows[:-1]
        if (r.get("メール") or "").strip() and (r.get("メール") or "").strip() != primary_email
    }
    for email in secondary_emails:
        await conn.execute(
            text(f"""
                INSERT INTO {schema}.staff_emails (staff_id, email, purpose)
                VALUES (:staff_id, :email, 'secondary')
                ON CONFLICT (staff_id, email) DO NOTHING
            """),
            {"staff_id": staff_id, "email": email},
        )
    if secondary_emails:
        logger.info("  %s: 副メール %d件を staff_emails に登録", staff_code, len(secondary_emails))

    # UI 設定
    await conn.execute(
        text(f"""
            INSERT INTO {schema}.staff_ui_preferences (
                staff_id, dark_mode,
                show_chat_menu, show_sales_menu, show_settings_menu,
                show_admin_menu, show_buddy_menu, show_sidebar
            ) VALUES (
                :staff_id, :dark_mode,
                :show_chat_menu, :show_sales_menu, :show_settings_menu,
                :show_admin_menu, :show_buddy_menu, :show_sidebar
            )
            ON CONFLICT (staff_id) DO UPDATE SET
                dark_mode = EXCLUDED.dark_mode,
                show_chat_menu = EXCLUDED.show_chat_menu,
                show_sales_menu = EXCLUDED.show_sales_menu,
                show_settings_menu = EXCLUDED.show_settings_menu,
                show_admin_menu = EXCLUDED.show_admin_menu,
                show_buddy_menu = EXCLUDED.show_buddy_menu,
                show_sidebar = EXCLUDED.show_sidebar,
                updated_at = NOW()
        """),
        {
            "staff_id": staff_id,
            "dark_mode": parse_bool_loose(main_row.get("ダークモード")),
            "show_chat_menu": parse_bool_loose(main_row.get("チャットメニュー表示")),
            "show_sales_menu": parse_bool_loose(main_row.get("営業メニュー表示")),
            "show_settings_menu": parse_bool_loose(main_row.get("設定メニュー表示")),
            "show_admin_menu": parse_bool_loose(main_row.get("管理者メニュー表示")),
            "show_buddy_menu": parse_bool_loose(main_row.get("Buddyメンテナンスメニュー表示")),
            "show_sidebar": parse_bool_loose(main_row.get("サイドバー表示")),
        },
    )

    logger.info(
        "  ✓ %s 投入: %s %s / 役割=%s / status=%s",
        staff_code, surname_jp, given_name_jp, role_name, status,
    )
    return staff_id


async def main() -> None:
    logger.info("=" * 72)
    logger.info("担当者マスタ移行開始: tenant_code=%s, csv=%s", TENANT_CODE, STAFF_CSV)
    logger.info("=" * 72)

    if not STAFF_CSV.exists():
        logger.error("CSV が見つかりません: %s", STAFF_CSV)
        sys.exit(1)

    engine = create_async_engine(DATABASE_URL, echo=False)
    try:
        tenant_id, schema = await get_tenant_info(engine, TENANT_CODE)
        logger.info("対象テナント: id=%d, schema=%s", tenant_id, schema)

        rows = load_staff_rows(STAFF_CSV)
        grouped = group_by_staff_code(rows)
        logger.info("ユニーク staff_code: %d", len(grouped))

        inserted = 0
        skipped = 0
        async with engine.begin() as conn:
            await conn.execute(text(f"SET search_path = {schema}, public"))
            await conn.execute(text(f"SET app.tenant_id = '{tenant_id}'"))

            for staff_code in sorted(grouped.keys()):
                staff_id = await insert_staff_with_related(
                    conn, schema, tenant_id, staff_code, grouped[staff_code]
                )
                if staff_id:
                    inserted += 1
                else:
                    skipped += 1

        logger.info("=" * 72)
        logger.info("✓ 担当者マスタ移行完了: 投入 %d件 / スキップ %d件", inserted, skipped)
        logger.info("=" * 72)
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
