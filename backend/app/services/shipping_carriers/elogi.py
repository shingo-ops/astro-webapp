from __future__ import annotations

"""
eLogi CSV adapter（ADR-021 Phase 3 / Sprint 3）。

Config.gs col 56-76 と同じ 19 列フォーマット:
  TIMESTAMP / SHIP_STAFF2 / ORDER_TYPE / ORDER_NO / ORDER_DATE /
  SKU2 / IMAGE_URL / PRODUCT_TITLE / QTY2 / USD_PRICE /
  BUYER_ID / RECIPIENT2 / PHONE2 / EMAIL2 / COUNTRY2 / STATE_CODE /
  CITY2 / ZIP2 / ADDRESS2_1

ADR-021 制約 5「eLogi CSV 出力フォーマット互換性」:
  eLogi 既存フォーマットを変更しない。列順 / ヘッダ名は固定。

入力フォーマット:
  router 側が組み立てる以下の構造の dict のリスト:
    {
      "order": {
        "id": int,
        "order_number": str,
        "order_date": str (ISO 形式の日付),
        "buyer_id": str | None,
        ...
      },
      "shipping": {  # order_shipping_details 行（None 許容）
        "recipient_name": str | None,
        "phone": str | None,
        ...
      },
      "extras": {  # eLogi 独自項目（OrderFlow 由来）
        "ship_staff": str | None,
        "order_type": str | None,
        "sku": str | None,
        "image_url": str | None,
        "product_title": str | None,
        "qty": int | None,
        "usd_price": Decimal | None,
        "timestamp": str | None,  # 出力時刻
      }
    }
  本 Sprint では DB に「商品 SKU / 画像 URL / 商品タイトル / 数量」を持つ列が
  まだないため、router は既存の order.notes 等から拾えるものだけ詰め、欠損は
  空文字で出す（eLogi 側がインポート時に補完する運用）。
"""

from datetime import datetime, timezone
from typing import Any, Iterable

from . import BaseCarrierAdapter


class ElogiCsvAdapter(BaseCarrierAdapter):
    carrier_code = "elogi"

    # Config.gs col 56-76 と完全一致させる（変更禁止）
    HEADER_COLUMNS = [
        "TIMESTAMP",
        "SHIP_STAFF2",
        "ORDER_TYPE",
        "ORDER_NO",
        "ORDER_DATE",
        "SKU2",
        "IMAGE_URL",
        "PRODUCT_TITLE",
        "QTY2",
        "USD_PRICE",
        "BUYER_ID",
        "RECIPIENT2",
        "PHONE2",
        "EMAIL2",
        "COUNTRY2",
        "STATE_CODE",
        "CITY2",
        "ZIP2",
        "ADDRESS2_1",
    ]

    def header_columns(self) -> list[str]:
        return list(self.HEADER_COLUMNS)

    def to_csv_lines(self, orders: Iterable[dict[str, Any]]) -> list[list[str]]:
        """受注 dict から 19 列の CSV 行を組み立てる。

        各 dict のキー（order / shipping / extras）の欠損は空文字。
        Decimal / int は str 化して出力する（CSV 上はすべて文字列）。
        """
        rows: list[list[str]] = []
        for entry in orders:
            order = entry.get("order") or {}
            shipping = entry.get("shipping") or {}
            extras = entry.get("extras") or {}

            timestamp = extras.get("timestamp") or _now_iso()

            row = [
                _s(timestamp),
                _s(extras.get("ship_staff")),
                _s(extras.get("order_type")),
                _s(order.get("order_number")),
                _s(_format_date(order.get("order_date") or order.get("created_at"))),
                _s(extras.get("sku")),
                _s(extras.get("image_url")),
                _s(extras.get("product_title")),
                _s(extras.get("qty")),
                _s(extras.get("usd_price")),
                _s(extras.get("buyer_id") or order.get("buyer_id")),
                _s(shipping.get("recipient_name")),
                _s(shipping.get("phone")),
                _s(shipping.get("email")),
                _s(shipping.get("country_code")),
                _s(shipping.get("state_code")),
                _s(shipping.get("city")),
                _s(shipping.get("zip_code")),
                _s(shipping.get("address1")),
            ]
            rows.append(row)
        return rows


def _s(value: Any) -> str:
    """None 安全な str 化。空 / None は空文字を返す。"""
    if value is None:
        return ""
    return str(value)


def _format_date(value: Any) -> str:
    """日付 / 日時を YYYY-MM-DD 形式に丸める。文字列はそのまま先頭 10 文字。"""
    if value is None:
        return ""
    if isinstance(value, datetime):
        return value.date().isoformat()
    s = str(value)
    # ISO 8601 (例: "2026-05-11T00:00:00+00:00") の先頭 10 文字を取る
    if len(s) >= 10 and s[4] == "-" and s[7] == "-":
        return s[:10]
    return s


def _now_iso() -> str:
    """エクスポート時刻（UTC ISO 8601、秒精度）。"""
    return datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
