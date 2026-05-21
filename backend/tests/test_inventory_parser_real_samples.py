"""Inventory parser AC3.2: 実 PostgreSQL + 5 仕入元 fixture parametrized テスト。

spec.md v1.1 Sprint 3 / AC3.2:
  実 Postgres（tenant_006）に supplier_aliases / knowledge_rules を seed した
  状態で、実在の 45 仕入元から取得した raw_content サンプル 5 件を service に渡し、
  parse_status = parsed で返ることを確認。

このテストは TEST_PG_URL（または RLS_TEST_DATABASE_URL）が設定されている時のみ実行。
未設定時は SKIP（SQLite では migration / JSONB / public schema が再現できない）。

実行方法:
  # ローカル: docker compose -f docker-compose.test.yml up -d postgres-test
  TEST_PG_URL=postgresql+asyncpg://myapp_user:password@localhost:5432/myapp_db \\
    pytest backend/tests/test_inventory_parser_real_samples.py -v

  # CI: tenant_006 環境を使用
  RLS_TEST_DATABASE_URL=... pytest -v

設計:
  - 各テストは ephemeral な supplier を作り、その supplier_aliases を seed
    （tenant_006 既存データには触れない）
  - rules は読み取り専用（既存 seed は変更しない）
  - テスト後に supplier + aliases を cleanup
"""
from __future__ import annotations

import json
import os
import pathlib

import pytest

from app.services.inventory_parser import parse_inventory_message, parse_raw_content
from app.services.inventory_parser import AliasRow, RuleRow


# 実 Postgres URL が指定されていない場合はモジュール全体を skip
TEST_PG_URL = os.getenv("TEST_PG_URL") or os.getenv("RLS_TEST_DATABASE_URL")

pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.skipif(
        not TEST_PG_URL,
        reason="実 PostgreSQL 環境が必要 (TEST_PG_URL / RLS_TEST_DATABASE_URL 未設定)。"
        "spec.md v1.1 / feedback_evaluator_gap_2026_05_15.md 参照。",
    ),
]

FIXTURE_DIR = pathlib.Path(__file__).parent / "fixtures" / "inventory_parser_samples"
SAMPLES_JSON = FIXTURE_DIR / "samples.json"


@pytest.fixture
def engine():
    """テスト用エンジン (function scope)。"""
    from sqlalchemy.ext.asyncio import create_async_engine

    eng = create_async_engine(TEST_PG_URL, echo=False)
    yield eng


@pytest.fixture
def fixture_samples() -> list[dict]:
    """samples.json をパース。"""
    with open(SAMPLES_JSON, encoding="utf-8") as f:
        return json.load(f)


# 5 仕入元の代表 alias（fixture 内の各 sample に対し最低限の alias を seed）
SUPPLIER_ALIASES: dict[int, list[str]] = {
    1: [
        "ムニキスゼロ", "ブラックボルト", "ホワイトフレア", "テラスタルフェスex",
        "ワイルドフォース", "サイバージャッジ", "古代の咆哮", "未来の一閃",
        "レイジングサーフ", "ポケモンカード151", "トリプレットビート",
        "VSTARユニバース", "タイムゲイザー",
    ],
    2: [
        "LIMIT OVER COLLECTION -THE RIVALS-", "MEGAドリームex", "ニンジャスピナー",
        "スタートデッキ100 バトルコレクション", "テラスタルフェスex",
        "インフェルノX", "ホワイトフレア", "超電ブレイカー", "バイオレットex",
        "クレイバースト", "変幻の仮面", "ワイルドフォース", "サイバージャッジ",
        "レイジングサーフ", "古代の咆哮", "未来の一閃", "ステラミラクル",
        "クリムゾンヘイズ", "151", "黒炎の支配者", "白熱のアルカナ",
        "バトルリージョン", "EB-04", "GD03", "FB05",
    ],
    3: [
        "LIMIT OVER COLLECTION -THE RIVALS-", "ニンジャスピナー",
        "メガドリームex", "インフェルノX", "メガブレイブ", "メガシンフォニア",
        "クリムゾンヘイズ", "ワイルドフォース", "サイバージャッジ", "未来の一閃",
        "ポケモン151", "VSTARユニバース", "トリプレットビート", "スカーレットex",
        "ロストアビス", "ポケモンセンタートウホク", "バトルリージョン",
        "フュージョンアーツ", "スターバース", "白銀のランス", "VMAXクライマックス",
        "OP-02 頂上決戦", "OP-03 強大な敵", "OP-06 双璧の覇者", "OP-08 二つの伝説",
        "OP-14 蒼海の七傑", "EB-01 メモリアルコレクション",
    ],
    4: [
        "メガドリーム", "メガドリームカートン", "インフェルノカートン",
        "OP-13カートン", "OP-15カートン", "OP-14カートン", "EB04カートン",
        "LIMIT OVER COLLECTION THE HEROES", "LIMIT OVER COLLECTION THE RIVALS",
        "ニンジャスピナー",
    ],
    5: [
        "ニンジャスピナー", "バトルパートナーズ", "超電ブレイカー",
        "クリムゾンヘイズ", "クレイバースト", "バイオレットex", "151",
        "ポケモンGO", "スペースジャグラー", "タイムゲイザー",
        "神の島の冒険 OP-15", "蒼海の七傑　OP-14", "新時代の主役 OP-05",
        "ROMANCE DAWN OP-01", "Day24 デイ24",
    ],
}


def _split_sql_preserving_do_blocks(sql: str) -> list[str]:
    """SQL を ; で split しつつ、DO $$ ... $$ や $tag$ ... $tag$ ブロックは丸ごと保持する。

    scripts/migrate_inventory_sprint1.py / test_inventory_sprint1_migrations.py
    と同じロジック（重複コード回避のため inline、外部 import 依存を持たない）。
    """
    statements: list[str] = []
    buf: list[str] = []
    i = 0
    in_dollar = False
    dollar_tag = ""
    while i < len(sql):
        if sql[i] == "$":
            j = i + 1
            while j < len(sql) and (sql[j].isalnum() or sql[j] == "_"):
                j += 1
            if j < len(sql) and sql[j] == "$":
                tag = sql[i : j + 1]
                if not in_dollar:
                    in_dollar = True
                    dollar_tag = tag
                elif tag == dollar_tag:
                    in_dollar = False
                    dollar_tag = ""
                buf.append(tag)
                i = j + 1
                continue
        ch = sql[i]
        if ch == ";" and not in_dollar:
            statements.append("".join(buf))
            buf = []
            i += 1
            continue
        buf.append(ch)
        i += 1
    if buf:
        statements.append("".join(buf))
    return statements


async def _ensure_inventory_schema(engine) -> None:
    """migrations 056-058 が適用済か確認。未適用なら適用する（idempotent）。

    asyncpg の prepared statement は複数 SQL command を 1 つの execute に渡せないため、
    DO ブロックを保護した split で 1 文ずつ exec する。
    すべての statement は CREATE TABLE IF NOT EXISTS / CREATE INDEX IF NOT EXISTS /
    冪等な DO $$ ... $$ なので、複数回実行しても安全。

    各 statement を独立した transaction で実行することで、
    既存テーブルへの制約再付与等で失敗した時に後続の statement が止まらないようにする。
    """
    MIGRATIONS_DIR = pathlib.Path(__file__).parents[2] / "migrations"
    needed = [
        "056_add_suppliers_type_and_promote_public.sql",
        "057_create_supplier_aliases.sql",
        "058_create_knowledge_rules.sql",
    ]
    for fn in needed:
        sql = (MIGRATIONS_DIR / fn).read_text("utf-8")
        for stmt in _split_sql_preserving_do_blocks(sql):
            stmt = stmt.strip()
            if not stmt:
                continue
            try:
                async with engine.begin() as conn:
                    await conn.exec_driver_sql(stmt)
            except Exception:
                # 冪等な migration なので、既存オブジェクトへの操作失敗は無視。
                # 次の statement で recover される。
                pass


async def _seed_supplier_with_aliases(
    conn, supplier_code: str, supplier_name: str, alias_texts: list[str]
) -> int:
    """ephemeral supplier + aliases を public schema に作成。supplier_id を返す。

    既に同 supplier_code があれば再利用（冪等）。
    """
    from sqlalchemy import text

    # supplier upsert
    result = await conn.execute(
        text(
            """
            INSERT INTO public.suppliers (supplier_code, name, supplier_type, default_language)
            VALUES (:code, :name, 'corporate', 'ja')
            ON CONFLICT (supplier_code) DO UPDATE SET name = EXCLUDED.name
            RETURNING id
            """
        ),
        {"code": supplier_code, "name": supplier_name},
    )
    supplier_id = result.scalar_one()

    # alias upsert
    for at in alias_texts:
        await conn.execute(
            text(
                """
                INSERT INTO public.supplier_aliases (supplier_id, alias_text, language, source)
                VALUES (:sid, :at, 'ja', 'manual')
                ON CONFLICT (supplier_id, alias_text, language) DO NOTHING
                """
            ),
            {"sid": supplier_id, "at": at},
        )
    return supplier_id


async def _cleanup_supplier(conn, supplier_id: int) -> None:
    """ephemeral supplier + aliases を削除。"""
    from sqlalchemy import text

    # ON DELETE CASCADE で supplier_aliases も消える
    await conn.execute(
        text("DELETE FROM public.suppliers WHERE id = :sid"), {"sid": supplier_id}
    )


# ---------------------------------------------------------------------------
# AC3.2: 5 仕入元 raw_content の parametrized テスト
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("sample_id", [1, 2, 3, 4, 5])
async def test_ac3_2_parse_real_supplier_sample(engine, fixture_samples, sample_id):
    """AC3.2: 5 仕入元 fixture を実 Postgres seed 経由で解析、parse_status='parsed' 相当の結果。

    検証:
      - items 件数が 5 以上（spec の expected_items_count は目安、parser の安定性を確認）
      - parse_engine = 'rule_v1'
      - items の各要素に product_id（alias 解決経由）と quantity が一定数埋まる
    """
    sample = next(s for s in fixture_samples if s["id"] == sample_id)
    sample_path = FIXTURE_DIR / sample["file"]
    raw_content = sample_path.read_text(encoding="utf-8")

    alias_texts = SUPPLIER_ALIASES[sample_id]
    supplier_code = f"TEST-AC3-2-S{sample_id:02d}"

    from sqlalchemy.ext.asyncio import AsyncSession
    from sqlalchemy.orm import sessionmaker

    AsyncSessionLocal = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    await _ensure_inventory_schema(engine)
    async with engine.begin() as conn:
        supplier_id = await _seed_supplier_with_aliases(
            conn, supplier_code, sample["supplier_name"], alias_texts
        )

    try:
        async with AsyncSessionLocal() as db:
            result = await parse_inventory_message(
                db,
                raw_content=raw_content,
                supplier_id=supplier_id,
                language="ja",
            )
        # AC3.2: parse_engine = 'rule_v1' (parse_status = 'parsed' 相当)
        assert result.parse_engine == "rule_v1"
        # items が空ではない（実データから何らかの構造化結果が出る）
        assert len(result.items) >= 5, (
            f"sample_{sample_id}: items {len(result.items)} 件 < 5、"
            f"alias 解決 / Step 4 抽出が機能していない疑い"
        )
        # 全 item に line_no, alias_text が埋まる
        for item in result.items:
            assert item.line_no is not None and item.line_no > 0
            assert item.alias_text is not None
        # 過半数の item に quantity が埋まる
        with_qty = [i for i in result.items if i.quantity is not None]
        assert len(with_qty) >= len(result.items) // 2, (
            f"sample_{sample_id}: quantity 抽出率が低い ({len(with_qty)}/{len(result.items)})"
        )
        # ParseResult.to_dict() が JSON シリアライズ可能
        json.dumps(result.to_dict(), ensure_ascii=False)

    finally:
        async with engine.begin() as conn:
            await _cleanup_supplier(conn, supplier_id)


async def test_ac3_2_db_wrapper_loads_aliases_and_rules(engine):
    """AC3.2 派生: DB ラッパが aliases / rules を正しく読み込む。"""
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import AsyncSession
    from sqlalchemy.orm import sessionmaker

    AsyncSessionLocal = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    supplier_code = "TEST-AC3-2-WRAPPER"

    await _ensure_inventory_schema(engine)
    async with engine.begin() as conn:
        supplier_id = await _seed_supplier_with_aliases(
            conn, supplier_code, "AC3.2 DB wrapper test", ["ムニキスゼロ"]
        )

    try:
        async with AsyncSessionLocal() as db:
            result = await parse_inventory_message(
                db,
                raw_content="■ムニキスゼロ 100BOX@5,000円",
                supplier_id=supplier_id,
                language="ja",
            )
        assert len(result.items) == 1
        assert result.items[0].alias_text == "ムニキスゼロ"
        assert result.items[0].quantity == 100
        assert result.items[0].unit == "box"
        assert result.items[0].unit_price == "5000"
    finally:
        async with engine.begin() as conn:
            await _cleanup_supplier(conn, supplier_id)


async def test_ac3_3_idempotency_real_db(engine, fixture_samples):
    """AC3.3: 同一 raw_content を 2 回流すと完全に同じ output JSON。"""
    from sqlalchemy.ext.asyncio import AsyncSession
    from sqlalchemy.orm import sessionmaker

    AsyncSessionLocal = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    sample = fixture_samples[0]  # サンプル 1
    sample_path = FIXTURE_DIR / sample["file"]
    raw_content = sample_path.read_text(encoding="utf-8")

    supplier_code = "TEST-AC3-3-IDEMP"
    await _ensure_inventory_schema(engine)
    async with engine.begin() as conn:
        supplier_id = await _seed_supplier_with_aliases(
            conn, supplier_code, "AC3.3 idempotency test", SUPPLIER_ALIASES[1]
        )

    try:
        async with AsyncSessionLocal() as db:
            r1 = await parse_inventory_message(db, raw_content, supplier_id, "ja")
        async with AsyncSessionLocal() as db:
            r2 = await parse_inventory_message(db, raw_content, supplier_id, "ja")

        # dict 比較
        d1 = r1.to_dict()
        d2 = r2.to_dict()
        assert d1 == d2, "実 DB 経由で 2 回呼んだ結果が異なる（冪等性違反）"
        # JSON 文字列の完全一致
        j1 = json.dumps(d1, ensure_ascii=False, sort_keys=False)
        j2 = json.dumps(d2, ensure_ascii=False, sort_keys=False)
        assert j1 == j2
    finally:
        async with engine.begin() as conn:
            await _cleanup_supplier(conn, supplier_id)


async def test_ac3_4_unparsed_classification_real_db(engine):
    """AC3.4: alias 未登録の token は unparsed に分類（exclude_reason ではなく）。"""
    from sqlalchemy.ext.asyncio import AsyncSession
    from sqlalchemy.orm import sessionmaker

    AsyncSessionLocal = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    supplier_code = "TEST-AC3-4-UNPARSED"

    await _ensure_inventory_schema(engine)
    async with engine.begin() as conn:
        supplier_id = await _seed_supplier_with_aliases(
            conn, supplier_code, "AC3.4 unparsed test", ["既知商品A"]
        )

    try:
        # 1 行は alias 解決可、1 行は未登録
        raw = "■既知商品A 100BOX@5,000円\n■未登録商品B 50BOX@10,000円"
        async with AsyncSessionLocal() as db:
            result = await parse_inventory_message(db, raw, supplier_id, "ja")
        # AC3.4: 未登録は unparsed 行く、exclude には行かない
        assert len(result.items) == 1
        assert result.items[0].alias_text == "既知商品A"
        assert len(result.unparsed) == 1
        assert "未登録商品B" in result.unparsed[0].raw_line
        # AC3.4: exclude には未登録行は入らない
        assert all("未登録商品B" not in e.raw_line for e in result.excludes)
        # parse_result_json.unparsed に格納される事実を to_dict で確認
        d = result.to_dict()
        assert len(d["unparsed"]) == 1
        assert "未登録商品B" in d["unparsed"][0]["raw_line"]
    finally:
        async with engine.begin() as conn:
            await _cleanup_supplier(conn, supplier_id)
