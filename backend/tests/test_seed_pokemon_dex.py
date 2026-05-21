"""seed_pokemon_dex.py の冪等性とローダー部分の単体テスト。

実 DB が必要な部分 (--apply) は実 PostgreSQL の TEST_PG_URL でのみ実行。
ロード/CSV パース部は SQLite 不要 (純粋関数) なので常時走る。

spec.md v1.1 AC1.4 関連:
  - 1025 行 (or fallback 25 行) を二度実行しても件数変化なし
  - --dry-run で DB 変更なし
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

# scripts/ を import できるようにパスを通す
_REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO_ROOT))

from scripts import seed_pokemon_dex  # noqa: E402

TEST_PG_URL = os.getenv("TEST_PG_URL")


def test_load_rows_fallback_when_csv_absent(tmp_path, monkeypatch):
    """CSV が無いとき fallback サンプル (25 行) を返す。"""
    # CSV_PATH を tmp_path 配下 (存在しない) に差し替え
    monkeypatch.setattr(
        seed_pokemon_dex,
        "CSV_PATH",
        tmp_path / "nonexistent.csv",
    )
    rows = seed_pokemon_dex._load_rows()
    assert len(rows) == 25
    assert rows[0][0] == 1  # dex 番号
    assert rows[0][1] == "フシギダネ"
    assert rows[0][2] == "Bulbasaur"
    assert rows[24][1] == "ピカチュウ"


def test_load_rows_from_csv(tmp_path, monkeypatch):
    """CSV があるとき CSV を読み込む。"""
    csv_path = tmp_path / "pokemon_dex.csv"
    csv_path.write_text(
        "dex_number,name_ja,name_en,generation,region\n"
        "1,フシギダネ,Bulbasaur,1,Kanto\n"
        "150,ミュウツー,Mewtwo,1,Kanto\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(seed_pokemon_dex, "CSV_PATH", csv_path)
    rows = seed_pokemon_dex._load_rows()
    assert len(rows) == 2
    assert rows[0] == (1, "フシギダネ", "Bulbasaur", 1, "Kanto")
    assert rows[1] == (150, "ミュウツー", "Mewtwo", 1, "Kanto")


def test_load_rows_rejects_invalid_csv_header(tmp_path, monkeypatch):
    """必須列が欠ける CSV はエラー。"""
    csv_path = tmp_path / "bad.csv"
    csv_path.write_text("dex,name\n1,foo\n", encoding="utf-8")
    monkeypatch.setattr(seed_pokemon_dex, "CSV_PATH", csv_path)
    with pytest.raises(ValueError, match="CSV ヘッダー不正"):
        seed_pokemon_dex._load_rows()


@pytest.mark.skipif(not TEST_PG_URL, reason="TEST_PG_URL が必要 (実 PostgreSQL)")
@pytest.mark.asyncio
async def test_seed_idempotency_real_postgres(monkeypatch):
    """AC1.4: 同じデータで 2 回 apply しても件数は変わらない (冪等性)。"""
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import create_async_engine

    # migration 061 を適用してテーブルを用意
    eng = create_async_engine(TEST_PG_URL, echo=False)
    try:
        # tcg_and_dex_masters migration 適用 (function 自動)
        from backend.tests.test_inventory_sprint1_migrations import _apply_public_migrations
        await _apply_public_migrations(eng)

        # apply 1 回目
        monkeypatch.setenv("DATABASE_URL", TEST_PG_URL)
        rows = seed_pokemon_dex._load_rows()
        await seed_pokemon_dex._seed(rows, dry_run=False)

        async with eng.connect() as conn:
            count_first = (await conn.execute(text(
                "SELECT COUNT(*) FROM public.pokemon_dex"
            ))).scalar_one()
        assert count_first == len(rows)

        # apply 2 回目
        await seed_pokemon_dex._seed(rows, dry_run=False)
        async with eng.connect() as conn:
            count_second = (await conn.execute(text(
                "SELECT COUNT(*) FROM public.pokemon_dex"
            ))).scalar_one()
        assert count_second == count_first, "冪等性違反: 2 回目で件数が変わった"
    finally:
        await eng.dispose()
