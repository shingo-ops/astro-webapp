from __future__ import annotations

"""
spec.md v1.1 F4 / Sprint 4: LLM フォールバック解析 (Gemini 2.5 Flash)。

F3 ルールベース解析 (`inventory_parser.parse_raw_content`) が unparsed[] を
返した行のみを Gemini 2.5 Flash に投げ、構造化抽出して items[] にマージする
ための薄い service レイヤ。

設計思想:
  - **structured output 強制**: `response_mime_type="application/json"` +
    `response_schema` で常に予測可能な JSON dict を返させる。
  - **prompt は短く**: unparsed_lines のみ + knowledge_rules スナップショット
    + 出力スキーマ。raw_content 全体は投げない（コスト抑制）。
  - **副作用なし**: DB アクセス・budget チェック・コスト記録は呼び出し側
    (inventory_parser.parse_inventory_message) の責務。本ファイルは純粋に
    API 呼び出しと JSON 整形だけ。
  - **API キー未設定 / 呼び出し失敗 = ParseError**: 呼び出し側が catch して
    parse_status='parsed_rule_only' に degrade (AC4.5)。
  - **retry / circuit breaker は入れない** (Generator 判断 3): 在庫メッセージ
    解析は1-shot OK、レート制限は budget で抑える。最小実装で着手 → 必要時
    別 ADR で追加。

参照:
  - .claude-pipeline/spec.md F4 (L139-155)
  - memory: project_jarvis_llm_gemini.md (Gemini 2.5 Flash 確定)
  - migration 059 (discord_inbound_messages.llm_cost_usd 列)
  - migration 062 (tenant_llm_budgets テーブル)
"""

import json
import logging
import os
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class LLMParseError(Exception):
    """Gemini 呼び出し失敗、API キー欠落、JSON パース失敗等を表す。

    呼び出し側 (parse_inventory_message) がこれを catch して
    parse_status='parsed_rule_only' に degrade する。
    """


class LLMConfigError(LLMParseError):
    """GEMINI_API_KEY が未設定 / 空。"""


# ---------------------------------------------------------------------------
# Public types
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class LLMParsedItem:
    """LLM が抽出した 1 行分の構造化結果。

    rule_v1 の ParsedItem と意図的に似せている (downstream マージ用)。
    product_id は LLM 側では解決しない (alias 照合は rule_v1 の責務、
    LLM はあくまで「数量 / 単価 / 名前 / 状態」の構造化のみ)。
    """

    raw_line: str
    line_no: int
    name: str
    quantity: int | None
    unit: str | None
    unit_price: float | None  # JSON 由来。Decimal は呼出側で必要時 cast
    condition: str | None
    confidence: float | None


@dataclass
class LLMParseResult:
    """parse_with_gemini() の戻り値。"""

    items: list[LLMParsedItem] = field(default_factory=list)
    # Gemini usage metadata からの token 数 (record_cost に渡す)
    input_tokens: int = 0
    output_tokens: int = 0
    model: str = "gemini-2.5-flash"
    raw_response_text: str = ""  # debug 用


# ---------------------------------------------------------------------------
# Output schema (Gemini structured output)
# ---------------------------------------------------------------------------

# Gemini SDK の response_schema は Python dict (OpenAPI schema subset) で渡す。
# 配列を nullable にしないこと（Gemini 側で SCHEMA_VALIDATION_FAILED になる）。
_OUTPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "items": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "raw_line": {"type": "string"},
                    "line_no": {"type": "integer"},
                    "name": {"type": "string"},
                    "quantity": {"type": "integer", "nullable": True},
                    "unit": {"type": "string", "nullable": True},
                    "unit_price": {"type": "number", "nullable": True},
                    "condition": {"type": "string", "nullable": True},
                    "confidence": {"type": "number", "nullable": True},
                },
                "required": ["raw_line", "line_no", "name"],
            },
        }
    },
    "required": ["items"],
}


# ---------------------------------------------------------------------------
# Prompt construction
# ---------------------------------------------------------------------------


def _build_prompt(
    unparsed_lines: list[dict[str, Any]],
    knowledge_snapshot: list[dict[str, Any]],
    language: str,
) -> str:
    """Gemini に投げる prompt 本文。

    入力:
      unparsed_lines: [{line_no: int, raw_line: str}, ...]
      knowledge_snapshot: [{pattern: str, normalized_to: str, category: str}, ...]
      language: 'ja' / 'en' / etc.
    """
    lines_block = "\n".join(
        f"  - L{ln['line_no']}: {ln['raw_line']}" for ln in unparsed_lines
    )
    # 重要な正規化規則だけ抜粋 (priority 高い順、上位 30 件)
    rules_block = "\n".join(
        f"  - '{r.get('pattern', '')}' → '{r.get('normalized_to', '')}' "
        f"(category={r.get('category', '?')})"
        for r in knowledge_snapshot[:30]
    )
    lang_instruction = {
        "ja": "出力 name は日本語の標準商品名で書いてください。",
        "en": "Output `name` should be the standard English product name.",
    }.get(language, "Output `name` should be a standard product name.")

    return f"""あなたは TCG (トレーディングカードゲーム) 在庫メッセージ解析アシスタントです。
Discord 仕入元から届いた在庫メッセージのうち、ルールベース解析エンジン (rule_v1)
が `unparsed` として返した行のみを再解析し、商品単位に分解してください。

# 入力 (unparsed 行のみ)
{lines_block}

# 既知の正規化規則 (knowledge_rules スナップショット、参考)
{rules_block}

# 出力要件
- {lang_instruction}
- quantity は数値のみ（box / pack / セット等の数量を整数で）
- unit は box / pack / set / piece / case のいずれか（不明なら null）
- unit_price は数値（円単位、不明なら null）
- condition は 'shrink' / 'no_shrink' / 'sealed' / 'damage' / 'unsearched' / 'searched' / 'graded' / 'grade_s' / 'grade_a' / 'grade_b' / 'grade_c' / 'grade_d' / 'junk' / 'bulk' / 'normal' / 'unknown' のいずれか（不明なら null）
- confidence は 0.0〜1.0 で推定信頼度
- 1 行から複数商品を抽出してよい（その場合は line_no を同じ値で複数 item に分割）
- 解析不能な行は items から除外 (報告しない)

JSON 形式で `{{"items": [...]}}` のみ返却してください。説明文 / コードブロック / 前置きは不要です。
"""


# ---------------------------------------------------------------------------
# Gemini SDK lazy initialization
# ---------------------------------------------------------------------------


_GENAI_CACHE: dict[str, Any] = {}


def _get_genai_module() -> Any:
    """`google.generativeai` を遅延 import (テスト時 mock 化のため)。

    SDK は import 時に何もしない (configure() で初めて API key 設定) ので、
    モジュールキャッシュだけ持つ。
    """
    if "module" not in _GENAI_CACHE:
        try:
            import google.generativeai as genai  # type: ignore[import-untyped]
        except ImportError as exc:
            raise LLMConfigError(
                "google-generativeai がインストールされていません。"
                "requirements.txt に追加されているか確認してください。"
            ) from exc
        _GENAI_CACHE["module"] = genai
    return _GENAI_CACHE["module"]


def _ensure_api_key() -> str:
    """env から GEMINI_API_KEY を取得。未設定なら LLMConfigError。"""
    key = os.getenv("GEMINI_API_KEY", "").strip()
    if not key:
        raise LLMConfigError(
            "GEMINI_API_KEY が未設定です。LLM フォールバックは無効化されます (AC4.5)。"
        )
    return key


# ---------------------------------------------------------------------------
# Main entry
# ---------------------------------------------------------------------------


async def parse_with_gemini(
    unparsed_lines: list[dict[str, Any]],
    knowledge_snapshot: list[dict[str, Any]],
    language: str = "ja",
    *,
    model_name: str = "gemini-2.5-flash",
) -> LLMParseResult:
    """unparsed 行を Gemini 2.5 Flash で再解析する。

    Args:
        unparsed_lines: rule_v1 が解けなかった行
            [{"line_no": int, "raw_line": str, "reason": str}, ...]
        knowledge_snapshot: 中央 knowledge_rules の参考スナップショット
            [{"pattern": ..., "normalized_to": ..., "category": ...}, ...]
        language: 'ja' / 'en' (default ja)
        model_name: 'gemini-2.5-flash' (default、別モデルは別 ADR)

    Returns:
        LLMParseResult: items + token 使用量

    Raises:
        LLMConfigError: GEMINI_API_KEY 未設定 / SDK 未 install
        LLMParseError:  Gemini 呼び出し / JSON パース失敗
    """
    if not unparsed_lines:
        # 呼び出し側のガードで普通は来ないが、空入力なら無料で空 result を返す
        return LLMParseResult(items=[], input_tokens=0, output_tokens=0, model=model_name)

    api_key = _ensure_api_key()
    genai = _get_genai_module()
    # SDK は process global 設定。スレッドセーフ。
    genai.configure(api_key=api_key)

    prompt = _build_prompt(unparsed_lines, knowledge_snapshot, language)

    # GenerationConfig で structured output を強制
    generation_config = {
        "response_mime_type": "application/json",
        "response_schema": _OUTPUT_SCHEMA,
        "temperature": 0.0,  # 冪等性を上げる
    }

    try:
        model = genai.GenerativeModel(
            model_name=model_name,
            generation_config=generation_config,
        )
        # generate_content は同期 / asyncio で wrap する版もあるが、SDK 0.8 では
        # 同期実装で十分（在庫メッセージ 1 件 数百 ms）。FastAPI worker に乗せる
        # 場合は run_in_executor で囲うこと。
        response = await _generate_content_async(model, prompt)
    except LLMParseError:
        raise
    except Exception as exc:  # noqa: BLE001 - SDK 例外を一元的に LLMParseError 化
        logger.exception("[llm_parser] Gemini call failed: %s", exc)
        raise LLMParseError(f"Gemini API 呼び出し失敗: {exc}") from exc

    text_payload = getattr(response, "text", "") or ""
    if not text_payload:
        raise LLMParseError("Gemini 応答が空でした")

    try:
        parsed = json.loads(text_payload)
    except json.JSONDecodeError as exc:
        raise LLMParseError(
            f"Gemini 応答が JSON ではありません: {text_payload[:200]!r}"
        ) from exc

    raw_items = parsed.get("items", []) if isinstance(parsed, dict) else []
    if not isinstance(raw_items, list):
        raise LLMParseError(
            f"Gemini 応答の items が配列ではありません: {type(raw_items).__name__}"
        )

    items: list[LLMParsedItem] = []
    for it in raw_items:
        if not isinstance(it, dict):
            continue
        # 必須列の最小バリデーション
        if "raw_line" not in it or "line_no" not in it or "name" not in it:
            continue
        items.append(
            LLMParsedItem(
                raw_line=str(it.get("raw_line", "")),
                line_no=int(it.get("line_no", 0)),
                name=str(it.get("name", "")),
                quantity=_safe_int(it.get("quantity")),
                unit=_safe_str_or_none(it.get("unit")),
                unit_price=_safe_float(it.get("unit_price")),
                condition=_safe_str_or_none(it.get("condition")),
                confidence=_safe_float(it.get("confidence")),
            )
        )

    usage = getattr(response, "usage_metadata", None)
    input_tokens = int(getattr(usage, "prompt_token_count", 0) or 0)
    output_tokens = int(getattr(usage, "candidates_token_count", 0) or 0)

    logger.info(
        "[llm_parser] Gemini call OK: items=%s in_tokens=%s out_tokens=%s",
        len(items),
        input_tokens,
        output_tokens,
    )
    return LLMParseResult(
        items=items,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        model=model_name,
        raw_response_text=text_payload,
    )


async def _generate_content_async(model: Any, prompt: str) -> Any:
    """Gemini SDK 同期 API を asyncio 経由で呼ぶ薄いラッパ。

    SDK 自体に async 版 (generate_content_async) があるならそちらを使う。
    AttributeError なら run_in_executor で同期版を thread に逃す。
    """
    if hasattr(model, "generate_content_async"):
        return await model.generate_content_async(prompt)
    # fallback: thread pool
    import asyncio

    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, model.generate_content, prompt)


def _safe_int(v: Any) -> int | None:
    if v is None:
        return None
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def _safe_float(v: Any) -> float | None:
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _safe_str_or_none(v: Any) -> str | None:
    if v is None or v == "":
        return None
    return str(v)


__all__ = [
    "LLMConfigError",
    "LLMParseError",
    "LLMParseResult",
    "LLMParsedItem",
    "parse_with_gemini",
]
