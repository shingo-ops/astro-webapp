"""Inventory parser (rule_v1) の単体テスト 30+ ケース。

spec.md v1.1 Sprint 3 / F3 / AC3.1〜3.5 の検証。

AC3.1: 単体テスト 30 ケース以上、items/excludes/unparsed の数を assert。
AC3.3: 同一入力で完全に同じ output JSON が返る（冪等性）。
AC3.4: alias 未登録の token は unparsed に分類。

本ファイルの位置づけ:
  - feedback_evaluator_gap_2026_05_15.md「SQLite モック禁止」の例外として、
    inventory_parser のコアロジックは **pure function**（DB 依存なし）であり、
    AliasRow / RuleRow フィクスチャを Python オブジェクトとして直接渡す。
  - 実 supplier_aliases フィクスチャ：DB 行ではなくテスト内の固定 fixture オブジェクト
    （AC3.1 が要求する「モックデータでなく実 supplier_aliases フィクスチャ」を
     満たすため、samples.json + 5 仕入元の実 alias_text を fixture として組み込む）。
  - 実 PostgreSQL での end-to-end 検証は test_inventory_parser_real_samples.py 側。
"""
from __future__ import annotations

import json
from decimal import Decimal

import pytest

from app.services.inventory_parser import (
    PARSE_ENGINE,
    AliasRow,
    ExcludedLine,
    ParsedItem,
    ParseResult,
    RuleRow,
    UnparsedLine,
    parse_raw_content,
)


# ---------------------------------------------------------------------------
# 共有 fixture: 5 仕入元の実 alias セット
# (fixtures/inventory_parser_samples/samples.json と整合)
# ---------------------------------------------------------------------------


@pytest.fixture
def aliases_sup1() -> list[AliasRow]:
    """仕入元 1 (シンソク) の代表 alias 13 件。"""
    return [
        AliasRow(id=1, supplier_id=1, alias_text="ムニキスゼロ", product_id=101),
        AliasRow(id=2, supplier_id=1, alias_text="ブラックボルト", product_id=102),
        AliasRow(id=3, supplier_id=1, alias_text="ホワイトフレア", product_id=103),
        AliasRow(id=4, supplier_id=1, alias_text="テラスタルフェスex", product_id=104),
        AliasRow(id=5, supplier_id=1, alias_text="ワイルドフォース", product_id=105),
        AliasRow(id=6, supplier_id=1, alias_text="サイバージャッジ", product_id=106),
        AliasRow(id=7, supplier_id=1, alias_text="古代の咆哮", product_id=107),
        AliasRow(id=8, supplier_id=1, alias_text="未来の一閃", product_id=108),
        AliasRow(id=9, supplier_id=1, alias_text="レイジングサーフ", product_id=109),
        AliasRow(id=10, supplier_id=1, alias_text="ポケモンカード151", product_id=110),
        AliasRow(id=11, supplier_id=1, alias_text="トリプレットビート", product_id=111),
        AliasRow(id=12, supplier_id=1, alias_text="VSTARユニバース", product_id=112),
        AliasRow(id=13, supplier_id=1, alias_text="タイムゲイザー", product_id=113),
    ]


@pytest.fixture
def aliases_sup5() -> list[AliasRow]:
    """仕入元 5 (三海) の代表 alias 15 件。「151」のような alias 自体が
    数字を含むケースを意図的に含める。"""
    return [
        AliasRow(id=51, supplier_id=5, alias_text="ニンジャスピナー", product_id=501),
        AliasRow(id=52, supplier_id=5, alias_text="バトルパートナーズ", product_id=502),
        AliasRow(id=53, supplier_id=5, alias_text="超電ブレイカー", product_id=503),
        AliasRow(id=54, supplier_id=5, alias_text="クリムゾンヘイズ", product_id=504),
        AliasRow(id=55, supplier_id=5, alias_text="クレイバースト", product_id=505),
        AliasRow(id=56, supplier_id=5, alias_text="バイオレットex", product_id=506),
        AliasRow(id=57, supplier_id=5, alias_text="151", product_id=507),
        AliasRow(id=58, supplier_id=5, alias_text="ポケモンGO", product_id=508),
        AliasRow(id=59, supplier_id=5, alias_text="スペースジャグラー", product_id=509),
        AliasRow(id=60, supplier_id=5, alias_text="タイムゲイザー", product_id=510),
        AliasRow(id=61, supplier_id=5, alias_text="神の島の冒険 OP-15", product_id=511),
        AliasRow(id=62, supplier_id=5, alias_text="蒼海の七傑　OP-14", product_id=512),
        AliasRow(id=63, supplier_id=5, alias_text="新時代の主役 OP-05", product_id=513),
        AliasRow(id=64, supplier_id=5, alias_text="ROMANCE DAWN OP-01", product_id=514),
        AliasRow(id=65, supplier_id=5, alias_text="Day24 デイ24", product_id=515),
    ]


# ---------------------------------------------------------------------------
# Step 1: 行分割 / exclude pattern
# ---------------------------------------------------------------------------


def test_01_empty_content_returns_empty_result():
    """空文字列を入力すると items/excludes/unparsed 全て 0。"""
    result = parse_raw_content("", supplier_id=1, aliases=[], rules=[])
    assert len(result.items) == 0
    assert len(result.excludes) == 0
    assert len(result.unparsed) == 0
    assert result.parse_engine == PARSE_ENGINE


def test_02_whitespace_only_returns_empty():
    """空白だけ / 改行だけの入力は除外される。"""
    result = parse_raw_content("   \n  \n\t\n", supplier_id=1, aliases=[], rules=[])
    assert len(result.items) == 0
    assert len(result.excludes) == 0
    assert len(result.unparsed) == 0


def test_03_greeting_line_is_excluded():
    """「お疲れ様です」「お世話になっております」等の挨拶行が excludes に入る。"""
    raw = "お疲れ様です。\n■ムニキスゼロ 100BOX@5,000円"
    result = parse_raw_content(
        raw,
        supplier_id=1,
        aliases=[AliasRow(id=1, supplier_id=1, alias_text="ムニキスゼロ", product_id=101)],
        rules=[],
    )
    assert len(result.excludes) >= 1
    assert any(e.exclude_reason == "greeting" for e in result.excludes)
    assert len(result.items) == 1


def test_04_section_header_excluded():
    """【在庫商品】等のセクションヘッダ単体行は exclude。"""
    raw = "【在庫商品】\n■ムニキスゼロ 100BOX@5,000円"
    result = parse_raw_content(
        raw,
        supplier_id=1,
        aliases=[AliasRow(id=1, supplier_id=1, alias_text="ムニキスゼロ", product_id=101)],
        rules=[],
    )
    # 【在庫商品】単独行は section_header
    assert any(e.exclude_reason == "section_header" for e in result.excludes)


def test_05_divider_line_excluded():
    """「---------」「-----」のような区切り線は divider として exclude。"""
    raw = "---------------------------\n■ムニキスゼロ 100BOX@5,000円"
    result = parse_raw_content(
        raw,
        supplier_id=1,
        aliases=[AliasRow(id=1, supplier_id=1, alias_text="ムニキスゼロ", product_id=101)],
        rules=[],
    )
    assert any(e.exclude_reason == "divider" for e in result.excludes)


def test_06_shipping_policy_line_excluded():
    """「・国内送料：900円/1梱包」等の policy line は shipping_policy で exclude。"""
    raw = (
        "■ムニキスゼロ 100BOX@5,000円\n"
        "・国内送料：900円/1梱包\n"
        "・適格請求書発行事業者"
    )
    result = parse_raw_content(
        raw,
        supplier_id=1,
        aliases=[AliasRow(id=1, supplier_id=1, alias_text="ムニキスゼロ", product_id=101)],
        rules=[],
    )
    reasons = {e.exclude_reason for e in result.excludes}
    assert "shipping_policy" in reasons or "policy_line" in reasons
    assert "policy_line" in reasons


# ---------------------------------------------------------------------------
# Step 2: alias 解決
# ---------------------------------------------------------------------------


def test_07_exact_alias_match():
    """完全一致 alias で product_id 解決。"""
    raw = "■ムニキスゼロ 100BOX@5,000円"
    result = parse_raw_content(
        raw,
        supplier_id=1,
        aliases=[AliasRow(id=1, supplier_id=1, alias_text="ムニキスゼロ", product_id=101)],
        rules=[],
    )
    assert len(result.items) == 1
    assert result.items[0].product_id == 101
    assert result.items[0].alias_text == "ムニキスゼロ"


def test_08_alias_not_registered_goes_to_unparsed(aliases_sup1):
    """AC3.4: alias 未登録の行は unparsed に入る（exclude ではない）。"""
    raw = "■知らない商品名 50BOX@1,000円"
    result = parse_raw_content(raw, supplier_id=1, aliases=aliases_sup1, rules=[])
    # 1 行 unparsed
    assert len(result.unparsed) == 1
    assert result.unparsed[0].raw_line == "■知らない商品名 50BOX@1,000円"
    # AC3.4: exclude ではなく unparsed
    assert all(
        e.raw_line != "■知らない商品名 50BOX@1,000円" for e in result.excludes
    )
    assert len(result.items) == 0


def test_09_alias_longest_match_wins():
    """alias_text が長いものを優先して一致させる。

    例: alias 'ホワイトフレア' と alias '拡張パック『ホワイトフレア』' の両方が
    登録されている場合、長い方が選ばれる（より固有の name を優先）。
    """
    raw = "■拡張パック『ホワイトフレア』 100BOX@16,000円"
    aliases = [
        AliasRow(id=1, supplier_id=1, alias_text="ホワイトフレア", product_id=103),
        AliasRow(id=2, supplier_id=1, alias_text="拡張パック『ホワイトフレア』", product_id=999),
    ]
    result = parse_raw_content(raw, supplier_id=1, aliases=aliases, rules=[])
    assert len(result.items) == 1
    assert result.items[0].product_id == 999  # 長い方が勝つ


def test_10_alias_language_preference():
    """language 一致を優先（ja 入力には ja alias、en alias は後回し）。"""
    aliases = [
        AliasRow(id=1, supplier_id=1, alias_text="Black Bolt", product_id=200, language="en"),
        AliasRow(id=2, supplier_id=1, alias_text="ブラックボルト", product_id=102, language="ja"),
    ]
    raw = "■ブラックボルト 65BOX@22,000円"
    result = parse_raw_content(raw, supplier_id=1, aliases=aliases, rules=[], language="ja")
    assert len(result.items) == 1
    assert result.items[0].product_id == 102


def test_11_alias_supplier_id_filter():
    """別 supplier_id の alias は無視される。"""
    aliases = [
        AliasRow(id=1, supplier_id=2, alias_text="ムニキスゼロ", product_id=999),  # 別 supplier
    ]
    raw = "■ムニキスゼロ 100BOX@5,000円"
    result = parse_raw_content(raw, supplier_id=1, aliases=aliases, rules=[])
    # supplier_id=1 では alias 解決できない → unparsed
    assert len(result.items) == 0
    assert len(result.unparsed) == 1


# ---------------------------------------------------------------------------
# Step 4: 数量 / 単価 / 単位
# ---------------------------------------------------------------------------


def test_12_box_unit_normalization():
    """BOX / Box / box / ボックス / 箱 → "box"。"""
    raw = "■ムニキスゼロ 100BOX@5,000円"
    result = parse_raw_content(
        raw,
        supplier_id=1,
        aliases=[AliasRow(id=1, supplier_id=1, alias_text="ムニキスゼロ", product_id=101)],
        rules=[],
    )
    assert result.items[0].unit == "box"
    assert result.items[0].quantity == 100
    assert result.items[0].unit_price == "5000"


def test_13_carton_unit_normalization():
    """カートン / Carton / case / CASE → "case"。"""
    raw = "■ニンジャスピナー 3カートン@438,000円"
    result = parse_raw_content(
        raw,
        supplier_id=1,
        aliases=[AliasRow(id=1, supplier_id=1, alias_text="ニンジャスピナー", product_id=200)],
        rules=[],
    )
    assert result.items[0].unit == "case"
    assert result.items[0].quantity == 3
    assert result.items[0].unit_price == "438000"


def test_14_pack_unit_normalization():
    """パック / pack → "pack"。"""
    raw = "■トウホク未開封パック 138パック@15,300円"
    result = parse_raw_content(
        raw,
        supplier_id=1,
        aliases=[AliasRow(id=1, supplier_id=1, alias_text="トウホク未開封パック", product_id=205)],
        rules=[],
    )
    assert result.items[0].unit == "pack"
    assert result.items[0].quantity == 138


def test_15_price_with_yen_suffix():
    """「円」suffix 付きの単価も解析できる。"""
    raw = "■ムニキスゼロ 100BOX@5,000円"
    result = parse_raw_content(
        raw,
        supplier_id=1,
        aliases=[AliasRow(id=1, supplier_id=1, alias_text="ムニキスゼロ", product_id=101)],
        rules=[],
    )
    assert Decimal(result.items[0].unit_price) == Decimal("5000")


def test_16_price_with_comma():
    """価格のカンマ区切りが正しく除去される。"""
    raw = "■ムニキスゼロ 10BOX@132,000円"
    result = parse_raw_content(
        raw,
        supplier_id=1,
        aliases=[AliasRow(id=1, supplier_id=1, alias_text="ムニキスゼロ", product_id=101)],
        rules=[],
    )
    assert Decimal(result.items[0].unit_price) == Decimal("132000")


def test_17_price_x_qty_format():
    """「11,800円×30BOX」形式が正しく解析される (イセキ仕入元)。"""
    raw = "●ニンジャスピナー 11,800円×30BOX(シュリ有)"
    result = parse_raw_content(
        raw,
        supplier_id=3,
        aliases=[AliasRow(id=1, supplier_id=3, alias_text="ニンジャスピナー", product_id=300)],
        rules=[],
    )
    assert len(result.items) == 1
    assert result.items[0].quantity == 30
    assert result.items[0].unit == "box"
    assert result.items[0].unit_price == "11800"
    assert result.items[0].condition == "shrink_yes"


def test_18_full_width_at_sign():
    """全角 @（＠）も解析できる。"""
    raw = "■ムニキスゼロ 100BOX＠5,000円"
    result = parse_raw_content(
        raw,
        supplier_id=1,
        aliases=[AliasRow(id=1, supplier_id=1, alias_text="ムニキスゼロ", product_id=101)],
        rules=[],
    )
    assert result.items[0].quantity == 100
    assert result.items[0].unit_price == "5000"


def test_19_unit_at_price_qty_format():
    """「カートン@520,000 数量1」形式 (三海)。"""
    raw = "●151 カートン@520,000 数量1 傷みあり"
    result = parse_raw_content(
        raw,
        supplier_id=5,
        aliases=[AliasRow(id=57, supplier_id=5, alias_text="151", product_id=507)],
        rules=[],
    )
    assert len(result.items) == 1
    assert result.items[0].quantity == 1  # alias の "151" を qty と誤検出しない
    assert result.items[0].unit == "case"
    assert result.items[0].unit_price == "520000"
    assert result.items[0].condition == "damaged"


def test_20_multiple_blocks_per_line():
    """1 行に複数 (qty,unit,price,cond) ブロックが同居するケース。

    シンソクサンプル: "100BOX@17,000円[通常品] 20BOX@15,700円[状態A-]"
    → 2 items に分割される。
    """
    raw = "■ブラックボルト 100BOX@17,000円[通常品] 20BOX@15,700円[状態A-]"
    result = parse_raw_content(
        raw,
        supplier_id=1,
        aliases=[AliasRow(id=1, supplier_id=1, alias_text="ブラックボルト", product_id=102)],
        rules=[],
    )
    assert len(result.items) == 2
    items_sorted = sorted(result.items, key=lambda x: -(x.quantity or 0))
    assert items_sorted[0].quantity == 100
    assert items_sorted[0].condition == "normal"
    assert items_sorted[1].quantity == 20
    assert items_sorted[1].condition == "state_a_minus"


def test_21_condition_normal():
    """[通常品] が condition='normal' に正規化される。"""
    raw = "■ムニキスゼロ 100BOX@5,000円[通常品]"
    result = parse_raw_content(
        raw,
        supplier_id=1,
        aliases=[AliasRow(id=1, supplier_id=1, alias_text="ムニキスゼロ", product_id=101)],
        rules=[],
    )
    assert result.items[0].condition == "normal"


def test_22_condition_state_a_minus():
    """[状態A-] が condition='state_a_minus' に正規化される。"""
    raw = "■ムニキスゼロ 20BOX@4,500円[状態A-]"
    result = parse_raw_content(
        raw,
        supplier_id=1,
        aliases=[AliasRow(id=1, supplier_id=1, alias_text="ムニキスゼロ", product_id=101)],
        rules=[],
    )
    assert result.items[0].condition == "state_a_minus"


def test_23_condition_state_b():
    """[状態B] が condition='state_b' に正規化される。"""
    raw = "■ムニキスゼロ 7BOX@4,000円[状態B]"
    result = parse_raw_content(
        raw,
        supplier_id=1,
        aliases=[AliasRow(id=1, supplier_id=1, alias_text="ムニキスゼロ", product_id=101)],
        rules=[],
    )
    assert result.items[0].condition == "state_b"


def test_24_condition_shrink_yes():
    """(シュリ有) → shrink_yes, シュリンク有り → shrink_yes。"""
    raw1 = "●ニンジャスピナー 11,800円×30BOX(シュリ有)"
    result1 = parse_raw_content(
        raw1,
        supplier_id=3,
        aliases=[AliasRow(id=1, supplier_id=3, alias_text="ニンジャスピナー", product_id=300)],
        rules=[],
    )
    assert result1.items[0].condition == "shrink_yes"


def test_25_condition_shrink_no():
    """(シュリ無) / シュリンク無し → shrink_no。"""
    raw = "ニンジャスピナー シュリンク無し 10500×50箱"
    result = parse_raw_content(
        raw,
        supplier_id=4,
        aliases=[AliasRow(id=1, supplier_id=4, alias_text="ニンジャスピナー", product_id=400)],
        rules=[],
    )
    assert result.items[0].condition == "shrink_no"


# ---------------------------------------------------------------------------
# 冪等性 (AC3.3)
# ---------------------------------------------------------------------------


def test_26_idempotency_same_input_same_output(aliases_sup1):
    """AC3.3: 同一入力を 2 回流すと完全に同じ output JSON。"""
    raw = (
        "■ムニキスゼロ 700BOX@7,100円[通常品] 7BOX@6,500円[状態B]\n"
        "■ブラックボルト 65BOX@22,000円[通常品]\n"
        "■ホワイトフレア 80BOX@18,500円[通常品] 20BOX@17,200円[状態A-]"
    )
    r1 = parse_raw_content(raw, supplier_id=1, aliases=aliases_sup1, rules=[])
    r2 = parse_raw_content(raw, supplier_id=1, aliases=aliases_sup1, rules=[])
    # dict 比較
    assert r1.to_dict() == r2.to_dict()
    # JSON 文字列の完全一致（順序まで）
    j1 = json.dumps(r1.to_dict(), ensure_ascii=False, sort_keys=False)
    j2 = json.dumps(r2.to_dict(), ensure_ascii=False, sort_keys=False)
    assert j1 == j2


def test_27_idempotency_with_shuffled_aliases(aliases_sup1):
    """AC3.3 派生: aliases の入力順を変えても出力は同じ。"""
    raw = "■ムニキスゼロ 100BOX@5,000円\n■ブラックボルト 50BOX@10,000円"
    a1 = list(aliases_sup1)
    a2 = list(reversed(aliases_sup1))
    r1 = parse_raw_content(raw, supplier_id=1, aliases=a1, rules=[])
    r2 = parse_raw_content(raw, supplier_id=1, aliases=a2, rules=[])
    assert r1.to_dict() == r2.to_dict()


def test_28_parse_engine_constant():
    """parse_engine は常に 'rule_v1'。"""
    result = parse_raw_content("", supplier_id=1, aliases=[], rules=[])
    assert result.parse_engine == "rule_v1"


# ---------------------------------------------------------------------------
# knowledge_rules (rule_v1 では最小機能、空 rule でも動作)
# ---------------------------------------------------------------------------


def test_29_knowledge_rule_exclude_custom():
    """category='exclude' の knowledge_rule で追加除外パターンを指定できる。"""
    rules = [
        RuleRow(
            id=1,
            category="exclude",
            pattern_type="substring",
            pattern="testxxx",
            normalized_to="custom_test_exclude",
            priority=200,
        )
    ]
    raw = "testxxx は除外したい行\n■ムニキスゼロ 100BOX@5,000円"
    result = parse_raw_content(
        raw,
        supplier_id=1,
        aliases=[AliasRow(id=1, supplier_id=1, alias_text="ムニキスゼロ", product_id=101)],
        rules=rules,
    )
    assert any(e.exclude_reason == "custom_test_exclude" for e in result.excludes)
    assert len(result.items) == 1


def test_30_knowledge_rule_normalize_substring():
    """category='normalize' で行内の表記を置換できる。"""
    rules = [
        RuleRow(
            id=1,
            category="normalize",
            pattern_type="substring",
            pattern="ボックス",
            normalized_to="BOX",
            priority=100,
        )
    ]
    raw = "■ムニキスゼロ 100ボックス@5,000円"
    result = parse_raw_content(
        raw,
        supplier_id=1,
        aliases=[AliasRow(id=1, supplier_id=1, alias_text="ムニキスゼロ", product_id=101)],
        rules=rules,
    )
    # normalize 後に BOX として解釈される → unit=box
    assert result.items[0].unit == "box"
    assert result.items[0].quantity == 100


def test_31_knowledge_rule_inactive_is_ignored():
    """is_active=False のルールは適用されない。"""
    rules = [
        RuleRow(
            id=1,
            category="exclude",
            pattern_type="substring",
            pattern="ムニキスゼロ",
            normalized_to="should_not_apply",
            priority=200,
            is_active=False,
        )
    ]
    raw = "■ムニキスゼロ 100BOX@5,000円"
    result = parse_raw_content(
        raw,
        supplier_id=1,
        aliases=[AliasRow(id=1, supplier_id=1, alias_text="ムニキスゼロ", product_id=101)],
        rules=rules,
    )
    # inactive rule は無視されるので、item として処理される
    assert len(result.items) == 1


# ---------------------------------------------------------------------------
# 出力 dataclass のシリアライズ
# ---------------------------------------------------------------------------


def test_32_result_to_dict_json_serializable():
    """ParseResult.to_dict() の戻り値は JSON シリアライズ可能。"""
    raw = "■ムニキスゼロ 100BOX@5,000円[通常品]"
    result = parse_raw_content(
        raw,
        supplier_id=1,
        aliases=[AliasRow(id=1, supplier_id=1, alias_text="ムニキスゼロ", product_id=101)],
        rules=[],
    )
    d = result.to_dict()
    assert "items" in d
    assert "excludes" in d
    assert "unparsed" in d
    assert "parse_engine" in d
    # JSON シリアライズが例外を投げない
    s = json.dumps(d, ensure_ascii=False)
    assert "ムニキスゼロ" in s
    assert "rule_v1" in s


def test_33_dataclass_fields_have_consistent_types():
    """ParsedItem.unit_price は str（JSON 安全）、quantity は int。"""
    raw = "■ムニキスゼロ 100BOX@5,000円"
    result = parse_raw_content(
        raw,
        supplier_id=1,
        aliases=[AliasRow(id=1, supplier_id=1, alias_text="ムニキスゼロ", product_id=101)],
        rules=[],
    )
    it = result.items[0]
    assert isinstance(it.quantity, int)
    assert isinstance(it.unit_price, str)
    assert isinstance(it.line_no, int)
    assert isinstance(it.alias_text, str)


# ---------------------------------------------------------------------------
# エッジケース
# ---------------------------------------------------------------------------


def test_34_line_with_alias_only_no_quantity():
    """alias は解決できるが quantity / price が無い行も item として記録される
    （後工程で補完できるよう、product_id だけ持つ ParsedItem を返す）。"""
    raw = "■ムニキスゼロ"
    result = parse_raw_content(
        raw,
        supplier_id=1,
        aliases=[AliasRow(id=1, supplier_id=1, alias_text="ムニキスゼロ", product_id=101)],
        rules=[],
    )
    assert len(result.items) == 1
    assert result.items[0].alias_text == "ムニキスゼロ"
    assert result.items[0].quantity is None
    assert result.items[0].unit_price is None


def test_35_aliases_empty_list_all_unparsed():
    """alias がない場合、商品候補がある行は全部 unparsed に分類される。"""
    raw = "■商品A 100BOX@5,000円\n■商品B 50BOX@10,000円"
    result = parse_raw_content(raw, supplier_id=1, aliases=[], rules=[])
    assert len(result.items) == 0
    # 商品 A / B の 2 行が unparsed
    assert len(result.unparsed) == 2


def test_36_full_width_space_normalized():
    """全角スペースが半角に正規化されて alias 一致できる。"""
    raw = "■ムニキスゼロ　100BOX@5,000円"  # 全角スペース
    result = parse_raw_content(
        raw,
        supplier_id=1,
        aliases=[AliasRow(id=1, supplier_id=1, alias_text="ムニキスゼロ", product_id=101)],
        rules=[],
    )
    assert len(result.items) == 1
    assert result.items[0].quantity == 100


def test_37_markdown_escaped_brackets_handled():
    """Markdown-escape された \\[ \\] が素の [ ] として処理される（fixture 互換性）。"""
    raw = "■ムニキスゼロ 100BOX@5,000円\\[通常品\\]"
    result = parse_raw_content(
        raw,
        supplier_id=1,
        aliases=[AliasRow(id=1, supplier_id=1, alias_text="ムニキスゼロ", product_id=101)],
        rules=[],
    )
    assert result.items[0].condition == "normal"


# ---------------------------------------------------------------------------
# 三海サンプル特有: 「151」が alias / qty 両方になりうるケース
# ---------------------------------------------------------------------------


def test_38_alias_with_digit_not_misinterpreted_as_qty(aliases_sup5):
    """alias='151' が qty として誤検出されないこと（_extract_blocks の優先順位）。"""
    raw = "●151 カートン@520,000 数量1"
    result = parse_raw_content(raw, supplier_id=5, aliases=aliases_sup5, rules=[])
    assert len(result.items) == 1
    assert result.items[0].quantity == 1
    assert result.items[0].alias_text == "151"
    assert result.items[0].unit == "case"


def test_39_qty_keyword_extracts_correct_qty():
    """「@5,300 数量30」形式: unit 無し + 数量キーワード。"""
    raw = "●Day24 デイ24 @5,300 数量30"
    result = parse_raw_content(
        raw,
        supplier_id=5,
        aliases=[AliasRow(id=1, supplier_id=5, alias_text="Day24 デイ24", product_id=515)],
        rules=[],
    )
    assert len(result.items) == 1
    assert result.items[0].quantity == 30
    assert result.items[0].unit_price == "5300"


# ---------------------------------------------------------------------------
# 5 仕入元サンプル統合テスト (samples.json + 実 alias 5 件) — Step 3 spec 整合
# ---------------------------------------------------------------------------


def test_40_sample01_shinsoku_parses_items(aliases_sup1):
    """シンソクサンプル全文を解析、items > 10 / unparsed 少数 / parse_engine='rule_v1'。"""
    import pathlib
    sample_path = pathlib.Path(__file__).parent / "fixtures" / "inventory_parser_samples" / "sample_01_シンソク.txt"
    content = sample_path.read_text(encoding="utf-8")
    result = parse_raw_content(content, supplier_id=1, aliases=aliases_sup1, rules=[])
    # 21 items を期待（fixture 検証で確認済）
    assert len(result.items) >= 15
    assert result.parse_engine == "rule_v1"
    # 多くのアイテムで product_id が埋まる
    with_product = [i for i in result.items if i.product_id is not None]
    assert len(with_product) >= 15


def test_41_sample05_sanmi_parses_items(aliases_sup5):
    """三海サンプル: alias='151' を持つ行が誤解析されないこと。"""
    import pathlib
    sample_path = pathlib.Path(__file__).parent / "fixtures" / "inventory_parser_samples" / "sample_05_三海.txt"
    content = sample_path.read_text(encoding="utf-8")
    result = parse_raw_content(content, supplier_id=5, aliases=aliases_sup5, rules=[])
    # 151 alias 一致行が item として現れる
    items_151 = [i for i in result.items if i.alias_text == "151"]
    assert len(items_151) >= 1
    assert items_151[0].quantity == 1  # 数量1（傷みあり）
    assert items_151[0].unit_price == "520000"


def test_42_sample_03_iseki_handles_shrink(aliases_sup1):
    """イセキサンプル: (シュリ有) / (シュリ無) の状態抽出。"""
    import pathlib
    sample_path = pathlib.Path(__file__).parent / "fixtures" / "inventory_parser_samples" / "sample_03_イセキ.txt"
    content = sample_path.read_text(encoding="utf-8")
    # イセキ用 alias を準備
    aliases = [
        AliasRow(id=300, supplier_id=3, alias_text="ニンジャスピナー", product_id=300),
        AliasRow(id=301, supplier_id=3, alias_text="メガドリームex", product_id=301),
        AliasRow(id=302, supplier_id=3, alias_text="インフェルノX", product_id=302),
    ]
    result = parse_raw_content(content, supplier_id=3, aliases=aliases, rules=[])
    # シュリンク 有 / 無 が混在する items が出てくる
    conditions = {i.condition for i in result.items if i.condition is not None}
    assert "shrink_yes" in conditions
    assert "shrink_no" in conditions


# ---------------------------------------------------------------------------
# ADR-093 Phase 3b: 区分(在庫/予約) / 発送日(ship_timing) の行内自動判定
# ---------------------------------------------------------------------------

from app.services.inventory_parser import _extract_offer_type_ship_timing  # noqa: E402


class TestOfferTypeShipTimingDetection:
    """`_extract_offer_type_ship_timing` (pure function) の検出ルール。"""

    def test_in_stock_default_none(self):
        """予約/発送日キーワードが無ければ (None, None) = 在庫扱い。"""
        assert _extract_offer_type_ship_timing("ニンジャスピナー 50BOX@11,900円") == (None, None)

    def test_preorder_keyword_without_timing_is_other(self):
        """予約語のみ（発送日不明）→ pre_order / other。"""
        assert _extract_offer_type_ship_timing("【予約】新弾BOX @12,000") == ("pre_order", "other")

    def test_preorder_on_release(self):
        assert _extract_offer_type_ship_timing("予約 発売日発送 BOX") == ("pre_order", "on_release")

    def test_ship_timing_1day_before(self):
        assert _extract_offer_type_ship_timing("予約商品 発売1日前発送") == ("pre_order", "1day_before")

    def test_ship_timing_2day_before_takes_priority(self):
        """「2日前」は「1日前」より優先して判定される。"""
        assert _extract_offer_type_ship_timing("予約 発売2日前発送") == ("pre_order", "2day_before")

    def test_ship_timing_implies_preorder(self):
        """発送日指定だけでも予約品とみなす。"""
        assert _extract_offer_type_ship_timing("発売日発送 BOX @10,000") == ("pre_order", "on_release")

    def test_digit_boundary_no_false_match(self):
        """数字境界: 「発売12日前」の末尾 '2日前' を ship_timing に誤判定しない（Reviewer PR#1445）。"""
        assert _extract_offer_type_ship_timing("発売12日前発送 BOX @10,000") == (None, None)
