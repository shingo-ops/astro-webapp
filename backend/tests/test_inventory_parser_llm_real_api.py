"""
spec.md v1.1 Sprint 4 / F4 / AC4.1: 実 Gemini API への 1 経路 (CI-only)。

feedback_evaluator_gap_2026_05_15.md の「SQLite モック禁止条項」遵守:
  - 本ファイルは **実 GEMINI_API_KEY** で Gemini 2.5 Flash を 1 回呼び、
    structured output が期待スキーマで返ることを確認する。
  - DB なし (pure Gemini 呼び出しのみ)、`tenant_llm_budgets` への record は
    別途 docs/runbooks/sprint-4-real-postgres-verification.md の手順で実 Postgres
    に対し実施する想定 (本テストはあくまで「LLM が叩けること」の証拠)。

  実 Gemini 呼び出しは課金対象 (1 回数十円〜数百円程度の極少額) なので、
  GEMINI_API_KEY が CI または developer ローカルにあるときだけ実行する。
  キー無しでは pytest.skip。

実行方法:
  pytest backend/tests/test_inventory_parser_llm_real_api.py -v
  (CI では GEMINI_API_KEY secret が flow 経由で env に注入される想定)
"""
from __future__ import annotations

import os

import pytest

from app.services.inventory_parser_llm import (
    LLMConfigError,
    LLMParseError,
    parse_with_gemini,
)


pytestmark = pytest.mark.skipif(
    not os.getenv("GEMINI_API_KEY", "").strip()
    or os.getenv("GEMINI_API_KEY", "").startswith("test-")
    or os.getenv("SKIP_REAL_LLM_TESTS", "").lower() in ("1", "true", "yes"),
    reason="実 GEMINI_API_KEY が未設定または test-* mock キー、または SKIP_REAL_LLM_TESTS=1",
)


@pytest.mark.asyncio
async def test_real_gemini_call_returns_structured_items() -> None:
    """実 Gemini 2.5 Flash を 1 回呼び、structured output が JSON で返ることを確認 (AC4.1)。

    確認内容:
        - 例外を投げずに完走する
        - items が list で返る
        - input_tokens / output_tokens が 0 より大きい (AC4.2 の前段)
        - 解析できれば name が含まれる
    """
    unparsed_lines = [
        {
            "line_no": 1,
            "raw_line": "リザードンex SAR シュリ有 3box 単価8000円",
            "reason": "no_alias_match",
        }
    ]
    knowledge_snapshot = [
        {"pattern": "リザex", "normalized_to": "リザードンex", "category": "alias"},
        {"pattern": "シュリ有", "normalized_to": "shrink", "category": "condition"},
    ]

    try:
        result = await parse_with_gemini(
            unparsed_lines=unparsed_lines,
            knowledge_snapshot=knowledge_snapshot,
            language="ja",
        )
    except LLMConfigError:
        pytest.skip("GEMINI_API_KEY 不正により skip")
    except LLMParseError as exc:
        pytest.fail(f"実 Gemini 呼び出しが失敗: {exc}")

    assert isinstance(result.items, list)
    # token 数が実値で記録される
    assert result.input_tokens > 0, "input_tokens should be > 0 for real API call"
    assert result.output_tokens > 0, "output_tokens should be > 0 for real API call"
    # モデル名が記録される
    assert result.model == "gemini-2.5-flash"
    # raw response が JSON
    assert result.raw_response_text.strip().startswith("{")

    # cost を概算してログに出す (デバッグ用、評価レポート用)
    from app.services.llm_budget import calculate_cost

    cost = calculate_cost(result.input_tokens, result.output_tokens)
    print(
        f"[real_api] input={result.input_tokens} output={result.output_tokens} "
        f"items={len(result.items)} cost_usd={cost}"
    )


@pytest.mark.asyncio
async def test_real_gemini_empty_unparsed_lines_no_call() -> None:
    """unparsed_lines が空なら、実 API を呼ばずに即 empty result が返る。"""
    result = await parse_with_gemini(unparsed_lines=[], knowledge_snapshot=[])
    assert result.items == []
    assert result.input_tokens == 0
    assert result.output_tokens == 0
