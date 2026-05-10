from __future__ import annotations

"""
配送キャリア adapter 層（ADR-021 Phase 3 / Sprint 3）。

将来の DHL / FedEx / ヤマト追加が単純な subclass で済む構造を提供する。
本 Sprint では eLogi のみ実装し、他キャリアは未実装（registry には eLogi のみ登録）。

設計:
  - BaseCarrierAdapter: 抽象基底クラス。`carrier_code` / `header_columns()` /
    `to_csv_lines(orders)` を subclass で実装する
  - CarrierRegistry: キャリアコード → adapter の lookup（重複登録は ValueError）
  - 文字エスケープ: CSV 仕様に従い、カンマ・改行・ダブルクォートを含む値は
    全体をダブルクォートで囲み、内部の " は "" にエスケープする（RFC 4180）

使い方（router 側）:
    from app.services.shipping_carriers import get_adapter

    adapter = get_adapter("elogi")
    csv_text = adapter.to_csv_text(orders)  # ヘッダ + データ行を改行区切りで返す

ADR-021 制約 5「eLogi CSV 出力フォーマット互換性」:
  eLogi 仕様変更がない限りフォーマットは変更しない。19 列の並び順 / ヘッダ名は
  Config.gs col 56-76 のまま。
"""

from abc import ABC, abstractmethod
from io import StringIO
from typing import Any, Iterable


class BaseCarrierAdapter(ABC):
    """配送キャリア adapter の抽象基底クラス。

    各キャリアごとに subclass を作成し、以下を実装する:
      - carrier_code (class attribute): "elogi" / "dhl" 等
      - header_columns(): ヘッダ行に出す列名のリスト（順序固定）
      - to_csv_lines(orders): 受注ごとの値を 2 次元リストとして返す
        （len = len(orders)、各 inner list は len = len(header_columns)）
    """

    #: キャリアコード（DB の carrier 列値と一致させる）。subclass で必ず override。
    carrier_code: str = ""

    @abstractmethod
    def header_columns(self) -> list[str]:
        """CSV ヘッダ行の列名リストを返す。"""
        raise NotImplementedError

    @abstractmethod
    def to_csv_lines(self, orders: Iterable[dict[str, Any]]) -> list[list[str]]:
        """受注 dict のイテラブルから CSV データ行を組み立てる。

        各 dict は `order` / `shipping` のサブ dict を持つ前提（router 側で
        構築する）。subclass は欠損値を空文字として扱うこと。
        """
        raise NotImplementedError

    def to_csv_text(self, orders: Iterable[dict[str, Any]]) -> str:
        """ヘッダ 1 行 + データ N 行の CSV テキストを返す。

        改行は `\r\n`（RFC 4180）。値のエスケープは _escape_csv_field に委譲。
        """
        buf = StringIO()
        header = self.header_columns()
        buf.write(",".join(_escape_csv_field(c) for c in header))
        buf.write("\r\n")
        for row in self.to_csv_lines(orders):
            # ヘッダと同じ列数を保証（subclass のバグで列ズレが起きるのを早期検出）
            if len(row) != len(header):
                raise ValueError(
                    f"adapter '{self.carrier_code}' produced row with "
                    f"{len(row)} columns, expected {len(header)}"
                )
            buf.write(",".join(_escape_csv_field(v) for v in row))
            buf.write("\r\n")
        return buf.getvalue()


def _escape_csv_field(value: Any) -> str:
    """CSV フィールド 1 つをエスケープする（RFC 4180 準拠）。

    - None は空文字
    - カンマ・ダブルクォート・改行を含む値は全体を " で囲み、内部の " は "" に
    - それ以外はそのまま str 化
    """
    if value is None:
        return ""
    s = str(value)
    if any(ch in s for ch in (",", '"', "\r", "\n")):
        escaped = s.replace('"', '""')
        return f'"{escaped}"'
    return s


class CarrierRegistry:
    """キャリアコード → adapter インスタンスの lookup。"""

    def __init__(self) -> None:
        self._adapters: dict[str, BaseCarrierAdapter] = {}

    def register(self, adapter: BaseCarrierAdapter) -> None:
        code = adapter.carrier_code
        if not code:
            raise ValueError("adapter must define non-empty carrier_code")
        if code in self._adapters:
            raise ValueError(f"adapter for '{code}' already registered")
        self._adapters[code] = adapter

    def get(self, code: str) -> BaseCarrierAdapter:
        if code not in self._adapters:
            raise KeyError(f"no adapter registered for carrier '{code}'")
        return self._adapters[code]

    def list_codes(self) -> list[str]:
        return sorted(self._adapters.keys())


# モジュール level の global registry。アプリ起動時に各 adapter を register する。
_REGISTRY = CarrierRegistry()


def get_adapter(carrier_code: str) -> BaseCarrierAdapter:
    """キャリアコードから adapter を取得する。"""
    return _REGISTRY.get(carrier_code)


def register_adapter(adapter: BaseCarrierAdapter) -> None:
    """adapter を registry に登録する（アプリ初期化時 / テスト用）。"""
    _REGISTRY.register(adapter)


def list_carrier_codes() -> list[str]:
    """登録済みキャリアコード一覧を返す。"""
    return _REGISTRY.list_codes()


# ---------------------------------------------------------------------------
# 既定 adapter の登録
# ---------------------------------------------------------------------------
# eLogi のみ本 Sprint で実装。DHL / FedEx / ヤマトは将来の Sprint で subclass を
# 追加して `register_adapter` するだけで済む構造。
from .elogi import ElogiCsvAdapter  # noqa: E402

try:
    register_adapter(ElogiCsvAdapter())
except ValueError:
    # テスト等で再 import される場合の冪等化
    pass
