from __future__ import annotations

"""
spec.md v1.1 F3 / Sprint 3: ルールベース在庫メッセージ解析エンジン (rule_v1)。

Discord 仕入元メッセージの raw_content を「商品 / 数量 / 単価 / 状態」に分解する
決定論的パイプライン。LLM 呼び出しは F4 (Sprint 4) で追加。

設計思想:
  - Pure function コア + DB 薄ラッパ
    parse_raw_content() は (raw_content, supplier_id, aliases, rules, language)
    を受け取り ParseResult を返す **副作用なし関数**。テストは alias/rule の
    fixture を Python dict で直接渡せば SQLite すら不要。
    parse_inventory_message() が DB から aliases/rules をロードして上を呼ぶ
    薄いラッパ。
  - 冪等性:
    同一入力 → 同一出力（dict 順, list 順まで決定論的）。
    rule の評価順は (priority DESC, id ASC) で安定ソート。
  - 表記ゆれ吸収:
    knowledge_rules が空でも動くように「ビルトインデフォルト」を持つ。
    BOX/Box/ボックス/カートン/case/パック/pack の正規化、@ / × の区切り、
    [通常品] / (シュリ有) 等の状態抽出を最初から備える。
  - 性能目標:
    1000 行 / 5 秒以内（AC3.5）。regex はモジュールスコープで pre-compile。

パイプライン:
  Step 1: 行分割 + exclude pattern 除去
  Step 2: supplier_aliases で完全 / 部分一致 → product_id 解決
  Step 3: knowledge_rules を priority 降順で適用 (text normalization)
  Step 4: 行内 token から quantity / unit_price / unit / condition 抽出

出力:
  ParseResult = {
    "items":     [ {raw_line, product_id, alias_text, qty, unit, unit_price,
                    condition, line_no, ...}, ... ],
    "excludes":  [ {raw_line, exclude_reason, line_no}, ... ],
    "unparsed":  [ {raw_line, line_no, reason}, ... ],
    "parse_engine": "rule_v1"
  }

関連:
  .claude-pipeline/spec.md F3
  migrations/057 (supplier_aliases)
  migrations/058 (knowledge_rules)
  backend/tests/fixtures/inventory_parser_samples/ (AC3.2 用 5 仕入元サンプル)
"""

import logging
import re
from dataclasses import asdict, dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

PARSE_ENGINE = "rule_v1"


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class AliasRow:
    """public.supplier_aliases の最小スナップショット（pure 関数入力用）。"""

    id: int
    supplier_id: int
    alias_text: str
    product_id: int | None
    language: str = "ja"
    confidence: float | None = None


@dataclass(frozen=True)
class RuleRow:
    """public.knowledge_rules の最小スナップショット（pure 関数入力用）。"""

    id: int
    category: str
    pattern_type: str  # 'regex' / 'prefix' / 'substring' / 'exact'
    pattern: str
    normalized_to: str | None = None
    priority: int = 100
    language: str = "ja"
    is_active: bool = True


@dataclass
class ParsedItem:
    """1 行分の構造化結果。"""

    raw_line: str
    line_no: int
    product_id: int | None = None
    alias_text: str | None = None
    product_name: str | None = None  # 正規化後の表記 (alias_text or normalized)
    quantity: int | None = None
    unit: str | None = None  # 'box' / 'case' / 'pack' / 'piece' / 'set'
    unit_price: str | None = None  # Decimal を JSON 安全に str で保持
    condition: str | None = None  # 'normal' / 'state_a_minus' / 'state_b' / 'shrink_yes' / 'shrink_no'
    raw_condition: str | None = None  # マッチした元テキスト
    notes: str | None = None  # 「シール有り」等の補足


@dataclass
class ExcludedLine:
    """exclude pattern で除外された行。"""

    raw_line: str
    line_no: int
    exclude_reason: str  # マッチした rule の category や説明


@dataclass
class UnparsedLine:
    """alias 未解決で構造化できなかった行（AC3.4）。"""

    raw_line: str
    line_no: int
    reason: str  # 'no_alias_match' / 'no_quantity' / etc.


@dataclass
class ParseResult:
    """F3 解析結果。`asdict()` で JSON 化可能。"""

    items: list[ParsedItem] = field(default_factory=list)
    excludes: list[ExcludedLine] = field(default_factory=list)
    unparsed: list[UnparsedLine] = field(default_factory=list)
    parse_engine: str = PARSE_ENGINE

    def to_dict(self) -> dict[str, Any]:
        """JSON 化用の dict 変換。dataclass の asdict を使い、None は維持。"""
        return {
            "items": [asdict(it) for it in self.items],
            "excludes": [asdict(ex) for ex in self.excludes],
            "unparsed": [asdict(up) for up in self.unparsed],
            "parse_engine": self.parse_engine,
        }


# ---------------------------------------------------------------------------
# Built-in defaults（knowledge_rules が空でも動くための最小辞書）
# ---------------------------------------------------------------------------

# 単位正規化: 表記ゆれを正規形に揃える。
# 「BOX / box / Box / ボックス / 箱」 → "box"
# 「カートン / Carton / CASE / case / ケース / CT」→ "case"
# 「パック / pack / Pack」→ "pack"
# 「set / セット」→ "set"
# 「枚」→ "piece"
DEFAULT_UNIT_NORMALIZATION: dict[str, str] = {
    "box": "box",
    "Box": "box",
    "BOX": "box",
    "ボックス": "box",
    "箱": "box",
    "カートン": "case",
    "carton": "case",
    "Carton": "case",
    "CARTON": "case",
    "case": "case",
    "Case": "case",
    "CASE": "case",
    "ケース": "case",
    "CT": "case",
    "ct": "case",
    "パック": "pack",
    "pack": "pack",
    "Pack": "pack",
    "PACK": "pack",
    "set": "set",
    "セット": "set",
    "枚": "piece",
}

# 「<num> <unit>」または「<unit> <num>」両対応の単位 token 集合。
# 検出用に union 正規表現を構築する（precompile）。
_UNIT_TOKENS = sorted(DEFAULT_UNIT_NORMALIZATION.keys(), key=len, reverse=True)
_UNIT_TOKEN_GROUP = "|".join(re.escape(u) for u in _UNIT_TOKENS)

# 数量+単位パターン:
#   "30BOX" "100ボックス" "5 カートン" "2 case" "138パック" "1set"
#   "×30BOX" "x 30 BOX" "×30箱"
# 単位の後ろに @ / × / x が来ても OK
QUANTITY_UNIT_RE = re.compile(
    rf"(\d{{1,5}})\s*(?:({_UNIT_TOKEN_GROUP}))",
    re.IGNORECASE,
)
# 「単位<数値>」順 (例: "カートン@340,000 数量2" は数量が後ろ)
# 数量=N 表記
QUANTITY_KEYWORD_RE = re.compile(r"(?:数量|qty|Qty|QTY|数)[\s=:]*?(\d{1,5})")

# 単価表記: "@7,100円" "@7100" "11,800円×30BOX" "9,500円×30BOX"
#          "× 31,000円" "11,800 円" "@340,000"
# 数字は 1〜3 桁 + (",000")* + ".00"? に対応。
# 末尾の「円」「JPY」「￥」「¥」も拾う。
PRICE_AT_RE = re.compile(r"[@＠]\s*([0-9][0-9,]{0,12}(?:\.\d+)?)")
PRICE_PLAIN_RE = re.compile(
    r"([0-9][0-9,]{2,12}(?:\.\d+)?)\s*(?:円|JPY|￥|¥)",
)
# 「11,800×30BOX」「14,800×200箱」「14,000×190BOX」「19,800x 8BOX」
# 単価 × 数量 + 単位
PRICE_MUL_QTY_RE = re.compile(
    rf"([0-9][0-9,]{{2,12}}(?:\.\d+)?)\s*(?:円)?\s*[×xX]\s*(\d{{1,5}})\s*(?:({_UNIT_TOKEN_GROUP}))?",
    re.IGNORECASE,
)

# 状態抽出:
#   [通常品] [状態A-] [状態B] [新品] [中古]
#   (シュリ有) (シュリ無) (シュリンク有) (シュリンク無) (シュリンクあり) (シュリンクなし)
#   括弧なし: "シュリンク無し" "シュリ有"
CONDITION_PATTERNS: list[tuple[str, str]] = [
    (r"\[\s*通常品\s*\]", "normal"),
    (r"\[\s*状態A[\-－—‐]\s*\]", "state_a_minus"),
    (r"\[\s*状態A\s*\]", "state_a"),
    (r"\[\s*状態B\s*\]", "state_b"),
    (r"\[\s*新品\s*\]", "new"),
    (r"\[\s*中古\s*\]", "used"),
    (r"[（(]\s*シュリ(?:ンク)?有(?:り)?\s*[）)]", "shrink_yes"),
    (r"[（(]\s*シュリ(?:ンク)?無(?:し)?\s*[）)]", "shrink_no"),
    (r"[（(]\s*シュリ(?:ンク)?あり\s*[）)]", "shrink_yes"),
    (r"[（(]\s*シュリ(?:ンク)?なし\s*[）)]", "shrink_no"),
    (r"シュリンク無し", "shrink_no"),
    (r"シュリンク有り", "shrink_yes"),
    (r"傷み(?:あり|有り)", "damaged"),
]
CONDITION_REGEXES: list[tuple[re.Pattern[str], str]] = [
    (re.compile(p), label) for p, label in CONDITION_PATTERNS
]

# Exclude pattern（既定）: rule で上書き / 追加可能
# 「※」「⚠️」「・配送」「・発送」「・適格」等のヘッダ / フッタ行
# 「【在庫商品】」「【予約商品】」等のセクションヘッダ
#
# TODO(Sprint 5 / Discord Bot 受信): policy_line の長大な alternation
# (100+ keywords) を public.knowledge_rules に DB seed として移行する。
# 現状の `policy_line` regex には「商品」「注文」「在庫」「TCG」「商品」等の
# 汎用語が含まれており、将来 supplier_aliases に
# 「商品リスト」「TCG カードゲーム」のような alias_text が登録されると
# `・商品リスト 100BOX@5,000円` のような商品行が誤って exclude される
# 可能性がある (Sprint 3 Reviewer Minor F1 / PR #514)。
# 移行方針:
#   1. migration 0XX で `public.knowledge_rules` に
#      `category='exclude' / pattern_type='regex' / language='ja'`
#      の seed 行として現在の各キーワードを個別 row 化
#   2. ホワイトリスト方式: 「行頭マーカ + キーワード」だけでなく、
#      「行末まで商品候補 token が無い」条件も加味するロジックを Sprint 5 で導入
#   3. デフォルトを最小限 (※/⚠️ + 配送/発送/税 専用) に縮退、運用は DB seed で
#   4. 監査ログ用 metadata (rule_id を ParseResult.excludes[].rule_id に残す)
# 本 PR (Sprint 2/3 follow-up) ではコメントのみ、実装は Sprint 5 で行う。
DEFAULT_EXCLUDE_REGEXES: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"^[\s]*(?:お疲れ様|お世話に|ご入用|ご注文|よろしく)"), "greeting"),
    (re.compile(r"^[\s]*(?:【.*?】)\s*$"), "section_header"),
    (re.compile(r"^[\s]*[-—=―ー\-]{3,}\s*$"), "divider"),
    (re.compile(r"^[\s]*(?:※|⚠️|◇|◆|・|◎|☆)\s*(?:適格|配送|発送|転送|国内|海外|出荷|出庫|転送|集荷|転送|秋葉|京都|東京|沖縄|北海道|箱の|緩衝|連絡|配送事故|運送|フライト|営業日|日曜|祝日|DHL|FedEx|ヤマト|問屋|買取|当社|弊社|税込|税抜|商品|本日|発送|破損|遅延|店頭|事務所|未開封|キャンセル|ラベル|テープ|マジック|ロット|追跡|管理番号|シール|プチプチ|請求書|販売数|数量が|納期|お問い合わせ|お振込|振込|お支払|入金|送料|割引|送料無料|状態|お渡し|引き渡し|引渡し|シュリンク|セール|割れ|破れ|箱|ご相談|お気軽|商品|TCG|個人LINE|LINE|個人|お疲れ|お世話|海外発送|転送サービス|サービス|転送|当日|発払い|集荷地域|地域|発送|出荷|発送地|店頭|販売|営業|電話|メール|LINE|ご質問|ご注文|配信|通知|メンション|くださ|お願|頂け|頂き|頂いて|頂ければ|致します|発生|破損|遅延|保証|承れ|責任|負い|可能性|なり|なる|なります|なります|お問合せ)"), "policy_line"),
    (re.compile(r"^[\s]*(?:商品の御提案|本日発送|当日18:00|⚠️記載商品)"), "policy_line"),
    (re.compile(r"^[\s]*(?:※|⚠️|◇|◆|・|◎|☆).{0,80}(?:円/1?梱包|円/梱包|円/個|発払い|集荷|転送)"), "shipping_policy"),
    (re.compile(r"^[\s]*(?:※|⚠️|◇|◆|・|◎|☆).{0,40}(?:適格請求|請求書|請求発行|発行事業者|発行可能|発行不可)"), "tax_policy"),
    (re.compile(r"^[\s]*(?:初めての方|メンション)"), "policy_line"),
]


# ---------------------------------------------------------------------------
# Step 1: 行分割 + exclude
# ---------------------------------------------------------------------------


def _split_into_lines(raw_content: str) -> list[str]:
    """raw_content を行に分割。

    実 Discord メッセージは改行 (\\n) と全角スペース、半角スペース混在のため、
    まず改行で分割し、各行から「・」「●」「■」「◆」「◇」等の箇条書き記号を
    取り除いて返す。空行は除外。

    Note: サンプル fixture を見ると改行が混在する場合と全文 1 行の場合がある。
    そのため全文 1 行のケースを救うため、まず「・」や「●」「■」を separator
    として候補に補い、複数行に分けてから処理する。
    """
    # 改行を normalize
    normalized = raw_content.replace("\r\n", "\n").replace("\r", "\n")
    # 全角スペース → 半角スペース（行内）
    normalized = normalized.replace("　", " ")
    # Markdown-escape されたブラケット `\[` `\]` を素の `[` `]` に戻す
    # （Discord メッセージを Markdown-render 用に escape したまま保存される fixture 対応）
    normalized = normalized.replace("\\[", "[").replace("\\]", "]")
    # Markdown-escape された「-」「(」「)」「*」も同様に戻す
    normalized = normalized.replace("\\-", "-").replace("\\(", "(").replace("\\)", ")")
    normalized = normalized.replace("\\*", "*").replace("\\_", "_")
    # 1 行に全部入っている fixture 救済: 行頭マーカ「・」「●」「■」「◆」の前に
    # 改行を挿入。「■拡張パック」のような連結を分離する。
    normalized = re.sub(r"(?<!^)[\s]*(?=[■●◆◇])", "\n", normalized)
    # 「・」は箇条書きの先頭にも policy line の先頭にも使われるが、行頭セパレータ
    # として有効なケースが多いので改行を入れる。ただし「・適格請求書」のような
    # policy line も改行されることになるが、exclude pattern で吸収される。
    normalized = re.sub(r"\s+・", "\n・", normalized)
    # 行頭マーカ「●」「■」「◆」「◇」「・」を保持したまま、改行で split。
    lines = [ln.strip() for ln in normalized.split("\n")]
    return [ln for ln in lines if ln]


def _build_exclude_regexes(rules: list[RuleRow]) -> list[tuple[re.Pattern[str], str]]:
    """category == 'exclude' の knowledge_rules を pre-compile + デフォルトと結合。

    DB rule が優先（priority 降順）→ デフォルト → 順に評価される。
    """
    custom: list[tuple[re.Pattern[str], str]] = []
    for r in rules:
        if r.category != "exclude" or not r.is_active:
            continue
        try:
            if r.pattern_type == "regex":
                custom.append((re.compile(r.pattern), r.normalized_to or f"rule_{r.id}"))
            elif r.pattern_type == "prefix":
                custom.append((re.compile("^" + re.escape(r.pattern)), r.normalized_to or f"rule_{r.id}"))
            elif r.pattern_type == "substring":
                custom.append((re.compile(re.escape(r.pattern)), r.normalized_to or f"rule_{r.id}"))
            elif r.pattern_type == "exact":
                custom.append((re.compile("^" + re.escape(r.pattern) + "$"), r.normalized_to or f"rule_{r.id}"))
            else:
                logger.warning("inventory_parser: unknown pattern_type=%s for rule_id=%s", r.pattern_type, r.id)
        except re.error as e:
            logger.warning("inventory_parser: invalid regex in rule_id=%s: %s", r.id, e)
    return custom + DEFAULT_EXCLUDE_REGEXES


def _apply_excludes(
    lines: list[str], exclude_regexes: list[tuple[re.Pattern[str], str]]
) -> tuple[list[tuple[int, str]], list[ExcludedLine]]:
    """exclude pattern にマッチした行を ExcludedLine へ、残りを (line_no, text) で返す。"""
    kept: list[tuple[int, str]] = []
    excluded: list[ExcludedLine] = []
    for line_no, line in enumerate(lines, start=1):
        matched_reason: str | None = None
        for pat, reason in exclude_regexes:
            if pat.search(line):
                matched_reason = reason
                break
        if matched_reason is not None:
            excluded.append(ExcludedLine(raw_line=line, line_no=line_no, exclude_reason=matched_reason))
        else:
            kept.append((line_no, line))
    return kept, excluded


# ---------------------------------------------------------------------------
# Step 2: supplier_aliases 解決
# ---------------------------------------------------------------------------


def _resolve_alias(
    line: str, aliases: list[AliasRow], language: str
) -> AliasRow | None:
    """alias_text が line に含まれるものを最長一致で 1 件返す。

    優先順位:
      1) language 一致のものを先に評価
      2) alias_text の長さが長いものを優先（より固有の名前にマッチさせる）
      3) confidence が高いものを優先
    """
    if not aliases:
        return None
    # language マッチを優先、ついで長さ降順、ついで confidence 降順
    sorted_aliases = sorted(
        aliases,
        key=lambda a: (
            0 if a.language == language else 1,
            -len(a.alias_text),
            -(a.confidence or 0.0),
            a.id,
        ),
    )
    for a in sorted_aliases:
        if not a.alias_text:
            continue
        if a.alias_text in line:
            return a
    return None


# ---------------------------------------------------------------------------
# Step 3: knowledge_rules による normalization（任意適用）
# ---------------------------------------------------------------------------


def _apply_normalization_rules(line: str, rules: list[RuleRow]) -> str:
    """category == 'normalize' / 'split' 等の rule を順次適用して line を書き換える。

    Step 3 は「行内の表現を正規形に置換する」最小機能のみ。priority 降順で
    安定ソート（同じ priority は id 昇順）。
    """
    work = line
    target_rules = [r for r in rules if r.category in {"normalize", "split", "alias_normalize"} and r.is_active]
    target_rules.sort(key=lambda r: (-r.priority, r.id))
    for r in target_rules:
        if r.normalized_to is None:
            continue
        try:
            if r.pattern_type == "regex":
                work = re.sub(r.pattern, r.normalized_to, work)
            elif r.pattern_type == "substring":
                work = work.replace(r.pattern, r.normalized_to)
            elif r.pattern_type == "prefix":
                if work.startswith(r.pattern):
                    work = r.normalized_to + work[len(r.pattern):]
            elif r.pattern_type == "exact":
                if work == r.pattern:
                    work = r.normalized_to
        except re.error as e:
            logger.warning("inventory_parser: invalid regex in normalize rule_id=%s: %s", r.id, e)
    return work


# ---------------------------------------------------------------------------
# Step 4: 数量 / 単価 / 単位 / 状態 抽出
# ---------------------------------------------------------------------------


def _parse_decimal(text_value: str) -> Decimal | None:
    """'7,100' / '340,000' / '7100' → Decimal('7100') 等に変換。失敗 None。"""
    try:
        cleaned = text_value.replace(",", "").strip()
        if not cleaned:
            return None
        return Decimal(cleaned)
    except (InvalidOperation, AttributeError):
        return None


def _extract_unit_quantity_price(line: str) -> tuple[int | None, str | None, Decimal | None]:
    """行から (quantity, unit, unit_price) を抽出。

    優先順位:
      1) 「PRICE × QTY UNIT」(例 "11,800円×30BOX") → 全部一度に取れる
      2) 「@PRICE」(単価のみ) + 「数量N」(数量のみ) → 後段で組み合わせ
      3) 「QTY UNIT @PRICE」(例 "30BOX@7,100円") → 全部取れる
      4) 数量・単位だけ取れる場合、単価は別の方法で探索
    """
    # ケース1: PRICE × QTY UNIT
    m = PRICE_MUL_QTY_RE.search(line)
    if m:
        price = _parse_decimal(m.group(1))
        qty_str = m.group(2)
        unit_raw = m.group(3)
        # 単価らしさチェック: 100 以上のときのみ単価とみなす（"1×30BOX" は単価ではない）
        if price is not None and price >= Decimal("100"):
            try:
                qty = int(qty_str)
            except ValueError:
                qty = None
            unit = DEFAULT_UNIT_NORMALIZATION.get(unit_raw, unit_raw) if unit_raw else None
            return qty, unit, price

    # ケース3: QTY UNIT @ PRICE
    qty_unit_match = QUANTITY_UNIT_RE.search(line)
    qty = None
    unit = None
    if qty_unit_match:
        try:
            qty = int(qty_unit_match.group(1))
        except ValueError:
            qty = None
        unit_raw = qty_unit_match.group(2)
        unit = DEFAULT_UNIT_NORMALIZATION.get(unit_raw, unit_raw)

    # 単価探索:
    price: Decimal | None = None
    at_match = PRICE_AT_RE.search(line)
    if at_match:
        price = _parse_decimal(at_match.group(1))
    if price is None:
        plain_match = PRICE_PLAIN_RE.search(line)
        if plain_match:
            price = _parse_decimal(plain_match.group(1))

    # 「数量」キーワード形式（@ 単価表記の後で出現する場合がある）
    if qty is None:
        qkw = QUANTITY_KEYWORD_RE.search(line)
        if qkw:
            try:
                qty = int(qkw.group(1))
            except ValueError:
                qty = None

    return qty, unit, price


def _extract_condition(line: str) -> tuple[str | None, str | None]:
    """行から (condition_normalized, raw_matched_text) を抽出。最初にマッチしたもの。"""
    for pat, label in CONDITION_REGEXES:
        m = pat.search(line)
        if m:
            return label, m.group(0)
    return None, None


# ---------------------------------------------------------------------------
# Step 4b: 1 行に複数 (qty × unit @ price [condition]) ブロックが含まれる場合の分割
# ---------------------------------------------------------------------------

# 「100BOX@17,000円[通常品] 20BOX@15,700円[状態A-]」のように
# 1 行に複数価格 / 数量 / 状態が同居するケースを切り分ける。
# パターン: <qty><unit>@<price>(?:\[<condition>\])?
# または:   <price>×<qty><unit> (シュリ有)?
PRICE_BLOCK_PATTERNS: list[re.Pattern[str]] = [
    # "30BOX@7,100円[通常品]"
    re.compile(
        rf"(\d{{1,5}})\s*({_UNIT_TOKEN_GROUP})\s*[@＠]\s*([0-9][0-9,]{{2,12}})\s*(?:円)?"
        rf"(?:\s*\[[^\]]+\])?",
        re.IGNORECASE,
    ),
    # "11,800円×30BOX(シュリ有)" or "11800×50箱"
    re.compile(
        rf"([0-9][0-9,]{{2,12}})\s*(?:円)?\s*[×xX]\s*(\d{{1,5}})\s*({_UNIT_TOKEN_GROUP})?"
        rf"(?:\s*\([^\)]+\))?",
        re.IGNORECASE,
    ),
    # "カートン@340,000 数量2" or "BOX @9,300 数量20"
    re.compile(
        rf"({_UNIT_TOKEN_GROUP})\s*[@＠]\s*([0-9][0-9,]{{2,12}})(?:\s*円)?"
        rf"\s*(?:数量|qty|QTY)\s*[:= ]?\s*(\d{{1,5}})",
        re.IGNORECASE,
    ),
]


def _extract_blocks(line: str) -> list[tuple[int | None, str | None, Decimal | None, str | None, str | None]]:
    """1 行から (qty, unit, price, condition, raw_condition) のタプル列を返す。

    複数ブロックがあれば複数返す。0 件なら [(None, None, None, None, None)] を返す。

    優先順位（行内に「数量N」キーワードが含まれるかで分岐）:
      行内に「数量\\d+」が含まれる場合 → unit@price + 数量qty 形式を先に試行
      含まれない場合 → qty unit @ price 形式を先に試行
    （三海サンプルの「●151 カートン@520,000 数量1」のように、alias 自体が
     数字を含むケースで qty を誤検出するのを避ける）
    """
    blocks: list[tuple[int | None, str | None, Decimal | None, str | None, str | None]] = []
    has_qty_keyword = bool(re.search(r"数量\s*\d+|qty\s*[:=]?\s*\d+", line, re.IGNORECASE))

    # 「数量N」キーワード有り: unit @ price + 数量qty を優先
    if has_qty_keyword:
        unit_at_price_qty = re.findall(
            rf"({_UNIT_TOKEN_GROUP})\s*[@＠]\s*([0-9][0-9,]{{2,12}})(?:\s*円)?"
            rf"\s*(?:数量|qty|QTY)\s*[:= ]?\s*(\d{{1,5}})",
            line,
            re.IGNORECASE,
        )
        if unit_at_price_qty:
            condition_line, raw_cond_line = _extract_condition(line)
            for m in unit_at_price_qty:
                unit_raw, price_str, qty_str = m
                qty = int(qty_str) if qty_str.isdigit() else None
                unit = DEFAULT_UNIT_NORMALIZATION.get(unit_raw, unit_raw)
                price = _parse_decimal(price_str)
                blocks.append((qty, unit, price, condition_line, raw_cond_line))
            return blocks

        # 単位なしで「@price 数量N」だけ (例: "Day24 デイ24 @5,300 数量30")
        at_price_qty = re.findall(
            r"[@＠]\s*([0-9][0-9,]{2,12})(?:\s*円)?\s*(?:数量|qty|QTY)\s*[:= ]?\s*(\d{1,5})",
            line,
            re.IGNORECASE,
        )
        if at_price_qty:
            condition_line, raw_cond_line = _extract_condition(line)
            for m in at_price_qty:
                price_str, qty_str = m
                qty = int(qty_str) if qty_str.isdigit() else None
                price = _parse_decimal(price_str)
                blocks.append((qty, None, price, condition_line, raw_cond_line))
            return blocks

    # 「数量N」キーワード無し: qty unit @ price [cond] を試行
    qty_unit_at_price = re.findall(
        rf"(\d{{1,5}})\s*({_UNIT_TOKEN_GROUP})\s*[@＠]\s*([0-9][0-9,]{{2,12}})\s*(?:円)?"
        rf"(\s*\[[^\]]+\])?",
        line,
        re.IGNORECASE,
    )
    if qty_unit_at_price:
        for m in qty_unit_at_price:
            qty_str, unit_raw, price_str, cond_raw = m
            qty = int(qty_str) if qty_str.isdigit() else None
            unit = DEFAULT_UNIT_NORMALIZATION.get(unit_raw, unit_raw)
            price = _parse_decimal(price_str)
            condition, raw_cond = _extract_condition(cond_raw) if cond_raw.strip() else (None, None)
            blocks.append((qty, unit, price, condition, raw_cond))
        return blocks

    # 価格×数量 形式: "11,800円×30BOX(シュリ有)" or "14,800×200箱"
    price_x_qty = re.findall(
        rf"([0-9][0-9,]{{2,12}})\s*(?:円)?\s*[×xX]\s*(\d{{1,5}})\s*({_UNIT_TOKEN_GROUP})?"
        rf"(\s*\([^\)]+\))?",
        line,
        re.IGNORECASE,
    )
    if price_x_qty:
        # 行全体から condition を取得（括弧外にある「シュリンク無し」等も拾う）
        line_condition, line_raw_cond = _extract_condition(line)
        for m in price_x_qty:
            price_str, qty_str, unit_raw, cond_raw = m
            price = _parse_decimal(price_str)
            qty = int(qty_str) if qty_str.isdigit() else None
            if price is None or price < Decimal("100"):
                # 「1×30BOX」のような数量行ノイズ除外
                continue
            unit = DEFAULT_UNIT_NORMALIZATION.get(unit_raw, unit_raw) if unit_raw else None
            # 括弧内 cond が無い場合は行全体の condition を使う
            if cond_raw.strip():
                condition, raw_cond = _extract_condition(cond_raw)
            else:
                condition, raw_cond = line_condition, line_raw_cond
            blocks.append((qty, unit, price, condition, raw_cond))
        if blocks:
            return blocks

    # フォールバック: 単一抽出
    qty, unit, price = _extract_unit_quantity_price(line)
    condition, raw_cond = _extract_condition(line)
    return [(qty, unit, price, condition, raw_cond)]


# ---------------------------------------------------------------------------
# Step 5: 1 行を ParsedItem / UnparsedLine に分類
# ---------------------------------------------------------------------------


def _classify_line(
    line_no: int,
    line: str,
    aliases: list[AliasRow],
    rules: list[RuleRow],
    language: str,
) -> tuple[list[ParsedItem], UnparsedLine | None]:
    """1 行を解析。alias と quantity の両方が取れれば ParsedItem(複数可)、
    そうでなければ UnparsedLine。

    1 行に複数 (qty,price,condition) ブロックが同居する場合は、各ブロックを
    1 つの ParsedItem として返す。

    AC3.4: alias 未登録の token は unparsed に分類される。
    """
    # Step 3: normalize（rule_v1 では空 rule のとき不変）
    normalized = _apply_normalization_rules(line, rules)

    # Step 2: alias 解決（正規化後の文字列で探索）
    alias = _resolve_alias(normalized, aliases, language)

    if alias is None:
        # AC3.4: alias 未登録 → unparsed
        # quantity が取れているかを参考情報として reason に含める
        qty, _u, _p = _extract_unit_quantity_price(normalized)
        reason = "no_alias_match" if qty is None else "no_alias_match_with_qty"
        return [], UnparsedLine(raw_line=line, line_no=line_no, reason=reason)

    # Step 4: 行内の複数ブロックを抽出
    blocks = _extract_blocks(normalized)

    # 「単価 0 / 数量 0 / 全部 None」なブロックを除外（ノイズ除去）
    cleaned = [b for b in blocks if not (b[0] is None and b[2] is None)]
    if not cleaned:
        # 単価も数量も取れない alias 一致行（"商品名のみ" など）は 1 item として記録
        cleaned = [(None, None, None, None, None)]

    items: list[ParsedItem] = []
    for qty, unit, price, condition, raw_cond in cleaned:
        items.append(
            ParsedItem(
                raw_line=line,
                line_no=line_no,
                product_id=alias.product_id,
                alias_text=alias.alias_text,
                product_name=alias.alias_text,
                quantity=qty,
                unit=unit,
                unit_price=str(price) if price is not None else None,
                condition=condition,
                raw_condition=raw_cond,
                notes=None,
            )
        )
    return items, None


# ---------------------------------------------------------------------------
# 公開 API: pure function
# ---------------------------------------------------------------------------


def parse_raw_content(
    raw_content: str,
    supplier_id: int,
    aliases: list[AliasRow],
    rules: list[RuleRow],
    language: str = "ja",
) -> ParseResult:
    """raw_content を ParseResult に変換する pure 関数。

    引数:
        raw_content: 仕入元 Discord メッセージの生テキスト
        supplier_id: 仕入元 ID（aliases の絞り込みは呼出側責務）
        aliases: 当該 supplier_id の alias 行リスト（呼出側でフィルタ済の想定）
        rules: knowledge_rules 全件（公開共通辞書）
        language: 'ja' / 'en' / 'ko' / 'zh' （default 'ja'）

    戻り値:
        ParseResult: items / excludes / unparsed / parse_engine='rule_v1'

    冪等性:
        同一入力に対し同一出力（リスト順含む）を保証する。
        rules はソートしてから評価、aliases は最長一致 + id tie-break で安定。

    AC3.5 性能:
        regex は precompile 済。aliases は最初に 1 回ソートして O(N*M) で
        全行を線形走査。1000 行で 5 秒以内（i5 ローカル < 1 秒、VPS 2GB < 2 秒見込み）。
    """
    # supplier_id でフィルタするのは呼出側責務とするが、念のため絞り込み
    relevant_aliases = [a for a in aliases if a.supplier_id == supplier_id]

    # Step 1: 行分割
    lines = _split_into_lines(raw_content)

    # exclude 構築（DB rule + デフォルト）
    exclude_regexes = _build_exclude_regexes(rules)
    kept, excluded = _apply_excludes(lines, exclude_regexes)

    # Step 2-4: 各行を分類
    items: list[ParsedItem] = []
    unparsed: list[UnparsedLine] = []
    for line_no, line in kept:
        line_items, unp = _classify_line(line_no, line, relevant_aliases, rules, language)
        items.extend(line_items)
        if unp is not None:
            unparsed.append(unp)

    # 出力順は line_no 昇順で安定（AC3.3 冪等性）
    # 同一 line_no 内では追加された順を保つ（dict 順 & list 順を変えない）
    items.sort(key=lambda x: x.line_no)
    excluded.sort(key=lambda x: x.line_no)
    unparsed.sort(key=lambda x: x.line_no)

    return ParseResult(items=items, excludes=excluded, unparsed=unparsed, parse_engine=PARSE_ENGINE)


# ---------------------------------------------------------------------------
# DB 薄ラッパ
# ---------------------------------------------------------------------------


async def _load_aliases_for_supplier(
    db: AsyncSession, supplier_id: int, language: str
) -> list[AliasRow]:
    """public.supplier_aliases から 当該 supplier_id の alias を読む。

    language は ja / en 両方拾う（fallback 用）。
    """
    result = await db.execute(
        text(
            """
            SELECT id, supplier_id, alias_text, product_id, language, confidence
              FROM public.supplier_aliases
             WHERE supplier_id = :sid
             ORDER BY id ASC
            """
        ),
        {"sid": supplier_id},
    )
    rows = result.mappings().all()
    return [
        AliasRow(
            id=r["id"],
            supplier_id=r["supplier_id"],
            alias_text=r["alias_text"],
            product_id=r["product_id"],
            language=r["language"],
            confidence=float(r["confidence"]) if r["confidence"] is not None else None,
        )
        for r in rows
    ]


async def _load_active_rules(db: AsyncSession) -> list[RuleRow]:
    """public.knowledge_rules から is_active=TRUE を全件読む。"""
    result = await db.execute(
        text(
            """
            SELECT id, category, pattern_type, pattern, normalized_to,
                   priority, language, is_active
              FROM public.knowledge_rules
             WHERE is_active = TRUE
             ORDER BY priority DESC, id ASC
            """
        )
    )
    rows = result.mappings().all()
    return [
        RuleRow(
            id=r["id"],
            category=r["category"],
            pattern_type=r["pattern_type"],
            pattern=r["pattern"],
            normalized_to=r["normalized_to"],
            priority=r["priority"],
            language=r["language"],
            is_active=r["is_active"],
        )
        for r in rows
    ]


async def parse_inventory_message(
    db: AsyncSession,
    raw_content: str,
    supplier_id: int,
    language: str = "ja",
    *,
    tenant_id: int | None = None,
) -> ParseResult:
    """DB から aliases / rules を読み込み、pure 関数を呼ぶ薄ラッパ。

    Sprint 4 (F4) で hybrid 化:
        - rule_v1 で unparsed があり、かつ tenant_id != None かつ budget が under なら
          Gemini 2.5 Flash で再解析し、結果を items[] にマージする。
        - 結果の `parse_engine`:
            - "rule_v1": tenant_id 未指定 / unparsed なし / Gemini key 不在 / Gemini 失敗
              → 純 rule_v1 結果 (parse_status は呼び出し側で parsed_rule_only)
            - "hybrid_rule_v1_llm_v1": Gemini が成功して item が増えた
            - "rule_v1_fallback_blocked": budget 超過で API 呼ばなかった (status=budget_exhausted)
        - 呼出側はこの parse_engine を見て `parse_status` を更新する。
          - hybrid_rule_v1_llm_v1 → parse_status='parsed_llm' or 'parsed'
          - rule_v1_fallback_blocked → parse_status='budget_exhausted'
          - rule_v1 (LLM 不在で degrade した場合) → parse_status='parsed_rule_only'

    使用例:
        from app.services.inventory_parser import parse_inventory_message
        result = await parse_inventory_message(
            db, raw_content, supplier_id=3, tenant_id=6
        )
        # result.parse_engine で status を判定し discord_inbound_messages に保存。

    Args:
        db: AsyncSession
        raw_content: 仕入元 Discord メッセージの生テキスト
        supplier_id: 仕入元 ID
        language: 'ja' / 'en' (default 'ja')
        tenant_id: budget 集計対象テナント。None なら LLM フォールバックを呼ばない
            (rule_v1 のみ。Sprint 3 までの動作と完全互換)。

    Returns:
        ParseResult: parse_engine は上記いずれか。items[] に LLM 由来も含まれる。
    """
    aliases = await _load_aliases_for_supplier(db, supplier_id, language)
    rules = await _load_active_rules(db)
    base = parse_raw_content(
        raw_content=raw_content,
        supplier_id=supplier_id,
        aliases=aliases,
        rules=rules,
        language=language,
    )

    # Sprint 3 互換: tenant_id 未指定 or unparsed なし → rule_v1 のみで終了
    if tenant_id is None or not base.unparsed:
        return base

    # LLM フォールバック経路
    return await _maybe_apply_llm_fallback(
        db=db,
        base_result=base,
        tenant_id=tenant_id,
        rules=rules,
        language=language,
    )


async def _maybe_apply_llm_fallback(
    db: AsyncSession,
    base_result: ParseResult,
    tenant_id: int,
    rules: list[RuleRow],
    language: str,
) -> ParseResult:
    """rule_v1 結果に LLM 由来 items をマージする。

    分岐:
        1. budget 月初リセット (reset_monthly_if_needed)
        2. budget チェック:
            - HARD_STOP / NO_BUDGET_ROW → parse_engine='rule_v1_fallback_blocked',
              admin に 1 回通知 (HARD_STOP のみ、NO_BUDGET_ROW は通知 skip)
            - UNDER / OVER_SOFT → Gemini 呼ぶ
        3. Gemini 呼び出し:
            - 成功 → items にマージ、record_cost で usage を加算、
              parse_engine='hybrid_rule_v1_llm_v1'
            - LLMConfigError (key 欠落) → rule_v1 のまま、parse_engine='rule_v1' 維持
              (呼出側で parsed_rule_only に降格)
            - LLMParseError (API 失敗) → 同上、log のみ
    """
    # 局所 import (循環防止 + DB 初期化前に google.generativeai を import しない)
    from app.services import discord_notifier, llm_budget
    from app.services.inventory_parser_llm import (
        LLMConfigError,
        LLMParseError,
        parse_with_gemini,
    )

    # Step 1: 月初リセット
    try:
        await llm_budget.reset_monthly_if_needed(db, tenant_id)
    except Exception as exc:  # noqa: BLE001 - budget エラーで解析を止めない
        logger.warning("[inventory_parser] budget reset failed: %s", exc)

    # Step 2: budget チェック
    status = await llm_budget.check_budget(db, tenant_id)
    if status in (
        llm_budget.BudgetStatus.HARD_STOP,
        llm_budget.BudgetStatus.NO_BUDGET_ROW,
    ):
        # 呼出側が parse_status='budget_exhausted' で記録する
        blocked = ParseResult(
            items=base_result.items,
            excludes=base_result.excludes,
            unparsed=base_result.unparsed,
            parse_engine="rule_v1_fallback_blocked",
        )
        if status == llm_budget.BudgetStatus.HARD_STOP:
            snap = await llm_budget.get_budget_snapshot(db, tenant_id)
            if snap is not None and snap.notify_admin:
                try:
                    await discord_notifier.notify_budget_exhausted(
                        db,
                        tenant_id,
                        monthly_budget_usd=snap.monthly_budget_usd,
                        current_month_usd=snap.current_month_usd,
                    )
                except Exception as exc:  # noqa: BLE001
                    logger.warning(
                        "[inventory_parser] discord notify failed: %s", exc
                    )
        return blocked

    # Step 3: Gemini 呼び出し
    unparsed_lines = [
        {"line_no": u.line_no, "raw_line": u.raw_line, "reason": u.reason}
        for u in base_result.unparsed
    ]
    knowledge_snapshot = [
        {
            "pattern": r.pattern,
            "normalized_to": r.normalized_to or "",
            "category": r.category,
        }
        for r in rules
    ]

    try:
        llm_result = await parse_with_gemini(
            unparsed_lines=unparsed_lines,
            knowledge_snapshot=knowledge_snapshot,
            language=language,
        )
    except LLMConfigError as exc:
        # API key 未設定: AC4.5 = graceful degrade (rule_v1 のみで終了)
        logger.info(
            "[inventory_parser] LLM disabled (config): %s, falling back to rule_v1",
            exc,
        )
        return base_result
    except LLMParseError as exc:
        logger.warning(
            "[inventory_parser] LLM call failed: %s, falling back to rule_v1", exc
        )
        return base_result

    # Step 4: コスト記録 (Gemini が tokens を返したら必ず記録)
    try:
        await llm_budget.record_cost(
            db,
            tenant_id,
            input_tokens=llm_result.input_tokens,
            output_tokens=llm_result.output_tokens,
            model=llm_result.model,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("[inventory_parser] record_cost failed: %s", exc)

    # Step 5: LLM 由来 items を rule_v1 items にマージ
    merged_items = list(base_result.items)
    llm_line_nos: set[int] = set()
    for item in llm_result.items:
        merged_items.append(_to_parsed_item_from_llm(item))
        llm_line_nos.add(item.line_no)

    # LLM が解けた line_no を unparsed から除外
    remaining_unparsed = [u for u in base_result.unparsed if u.line_no not in llm_line_nos]

    merged_items.sort(key=lambda x: x.line_no)
    remaining_unparsed.sort(key=lambda x: x.line_no)

    return ParseResult(
        items=merged_items,
        excludes=base_result.excludes,
        unparsed=remaining_unparsed,
        parse_engine="hybrid_rule_v1_llm_v1",
    )


def _to_parsed_item_from_llm(llm_item: Any) -> ParsedItem:
    """LLMParsedItem を ParsedItem に変換。

    rule_v1 と同じ列構造を維持。product_id は LLM 側では解決しないので None。
    product_name に LLM 出力 name を入れる (alias_text 列は alias 由来時のみ使用)。
    unit_price は ParsedItem 仕様に従い str (Decimal を JSON 安全に保持)。
    confidence は notes に「llm_v1 confidence=0.X」として記録する (column 追加なし)。
    """
    # quantity は ParsedItem 仕様で int (rule_v1 ベースでは int で扱われている)
    qty_value: int | None = None
    if llm_item.quantity is not None:
        try:
            qty_value = int(llm_item.quantity)
        except (TypeError, ValueError):
            qty_value = None

    # unit_price は str で保存 (ParsedItem.unit_price: str | None)
    price_str: str | None = None
    if llm_item.unit_price is not None:
        try:
            price_str = str(Decimal(str(llm_item.unit_price)))
        except InvalidOperation:
            price_str = None

    notes_parts: list[str] = ["source=llm_v1"]
    if llm_item.confidence is not None:
        notes_parts.append(f"confidence={llm_item.confidence:.2f}")
    notes_value = "; ".join(notes_parts)

    return ParsedItem(
        raw_line=llm_item.raw_line,
        line_no=llm_item.line_no,
        product_id=None,
        alias_text=None,
        product_name=llm_item.name or None,
        quantity=qty_value,
        unit=llm_item.unit,
        unit_price=price_str,
        condition=llm_item.condition,
        raw_condition=None,
        notes=notes_value,
    )


__all__ = [
    "PARSE_ENGINE",
    "AliasRow",
    "RuleRow",
    "ParsedItem",
    "ExcludedLine",
    "UnparsedLine",
    "ParseResult",
    "parse_raw_content",
    "parse_inventory_message",
    "DEFAULT_UNIT_NORMALIZATION",
]
