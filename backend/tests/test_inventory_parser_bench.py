"""Inventory parser (rule_v1) のパフォーマンスベンチ (AC3.5)。

AC3.5: 解析速度ベンチ: 1000 行 raw_content を 5 秒以内に処理（VPS 2GB 環境想定、
R5 SLO 内、ローカルベンチで PASS なら OK、VPS 実機は Evaluator 持ち）。

このテストはローカルで PASS する必要があり、CI でも実行される（環境変数で
SKIP_BENCH=1 を立てると skip 可能）。

実行方法:
  cd astro-webapp/backend
  pytest tests/test_inventory_parser_bench.py -v
  # 個別 marker 指定で:
  pytest -k bench -v
"""
from __future__ import annotations

import os
import time

import pytest

from app.services.inventory_parser import AliasRow, parse_raw_content


pytestmark = pytest.mark.skipif(
    os.getenv("SKIP_BENCH") == "1",
    reason="SKIP_BENCH=1 で bench skip（CI 時短）",
)


@pytest.fixture
def aliases_bench() -> list[AliasRow]:
    """ベンチ用 alias 20 件（実 5 仕入元の代表）。"""
    return [
        AliasRow(id=i, supplier_id=1, alias_text=name, product_id=i)
        for i, name in enumerate(
            [
                "ムニキスゼロ", "ブラックボルト", "ホワイトフレア", "テラスタルフェスex",
                "ワイルドフォース", "サイバージャッジ", "古代の咆哮", "未来の一閃",
                "レイジングサーフ", "ポケモンカード151", "トリプレットビート",
                "VSTARユニバース", "タイムゲイザー", "ニンジャスピナー",
                "MEGAドリームex", "インフェルノX", "クリムゾンヘイズ",
                "クレイバースト", "バイオレットex", "151",
            ],
            start=1,
        )
    ]


def _build_long_raw(n_lines: int, aliases: list[AliasRow]) -> str:
    """n_lines 行の擬似 raw_content を構築。alias が周期的に出現する。"""
    lines: list[str] = []
    n_aliases = len(aliases)
    for i in range(n_lines):
        alias = aliases[i % n_aliases]
        qty = (i % 100) + 1
        price = ((i * 137) % 50000) + 1000
        # 30% の行は [通常品]、20% は [状態A-]、残りは無条件
        if i % 10 < 3:
            cond = "[通常品]"
        elif i % 10 < 5:
            cond = "[状態A-]"
        else:
            cond = ""
        lines.append(f"■{alias.alias_text} {qty}BOX@{price:,}円{cond}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# AC3.5 ベンチ本体
# ---------------------------------------------------------------------------


@pytest.mark.bench
def test_ac3_5_bench_1000_lines_under_5_seconds(aliases_bench):
    """AC3.5: 1000 行 raw_content を 5 秒以内に処理。

    ローカル開発機（i5 / M1 等）では 1 秒以内が目安。
    VPS 2GB / メモリ headroom 狭い環境を想定して 5 秒の余裕を取る。
    """
    raw = _build_long_raw(1000, aliases_bench)
    # warmup
    parse_raw_content(raw, supplier_id=1, aliases=aliases_bench, rules=[])

    start = time.perf_counter()
    result = parse_raw_content(raw, supplier_id=1, aliases=aliases_bench, rules=[])
    elapsed = time.perf_counter() - start

    assert elapsed < 5.0, f"1000 行解析が {elapsed:.2f} 秒、SLO 5 秒を超過"
    # item は最低でも 500 行は解析できているはず（条件タグ付きで複数 block の場合あり）
    assert len(result.items) >= 500
    print(f"\n[bench] 1000 行解析: {elapsed*1000:.1f}ms / items={len(result.items)}")


@pytest.mark.bench
def test_ac3_5_bench_idempotency_at_scale(aliases_bench):
    """大規模入力でも冪等性が保たれる（AC3.3 派生）。"""
    raw = _build_long_raw(500, aliases_bench)
    r1 = parse_raw_content(raw, supplier_id=1, aliases=aliases_bench, rules=[])
    r2 = parse_raw_content(raw, supplier_id=1, aliases=aliases_bench, rules=[])
    assert r1.to_dict() == r2.to_dict()


@pytest.mark.bench
def test_ac3_5_bench_2000_lines_still_reasonable(aliases_bench):
    """2000 行でも 10 秒以内（線形性確認、SLO 直接の AC ではないが回帰防止）。"""
    raw = _build_long_raw(2000, aliases_bench)
    start = time.perf_counter()
    result = parse_raw_content(raw, supplier_id=1, aliases=aliases_bench, rules=[])
    elapsed = time.perf_counter() - start
    assert elapsed < 10.0, f"2000 行で {elapsed:.2f} 秒、線形性が崩れた疑い"
    assert len(result.items) >= 1000
    print(f"\n[bench] 2000 行解析: {elapsed*1000:.1f}ms / items={len(result.items)}")
