"""
spec.md v1.1 Sprint 4 / F4 / AC4.1〜4.5: LLM フォールバック解析の単体テスト。

cover:
  AC4.1: unparsed 行があれば Gemini を 1 回呼ぶ
  AC4.2: usage_metadata から token 数を取り cost を算出
  AC4.3: budget HARD_STOP で API 呼ばない
  AC4.4: 月初リセット呼び出しが parse 冒頭で走る
  AC4.5: API key 不在 / 失敗時は graceful degrade (parse_engine='rule_v1' のまま)
  追加: hybrid_rule_v1_llm_v1 のマージ動作、unparsed 行が空なら呼ばない etc.

feedback_evaluator_gap_2026_05_15.md「SQLite モック禁止」例外:
  inventory_parser_llm は外部 SDK (google-generativeai) との結合層のため、
  単体テストではモック必須 (本物の API を毎回叩くと CI 失敗 / 課金)。
  実 API 経由の 1 経路は test_inventory_parser_llm_real_api.py (CI-only) で別途検証。

Mock 戦略:
  - google.generativeai モジュール全体を MagicMock で差し替え
  - inventory_parser_llm._GENAI_CACHE に MagicMock を事前注入
  - response.text に JSON 文字列を返させて生 response をシミュレート
  - usage_metadata を MagicMock で生成
"""
from __future__ import annotations

import json
import os
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services import inventory_parser_llm
from app.services.inventory_parser_llm import (
    LLMConfigError,
    LLMParseError,
    LLMParsedItem,
    LLMParseResult,
    parse_with_gemini,
)


# ---------------------------------------------------------------------------
# Helpers: 偽 Gemini response のファクトリ
# ---------------------------------------------------------------------------


def _make_fake_response(
    json_payload: dict | None = None,
    text_payload: str | None = None,
    prompt_tokens: int = 1200,
    candidates_tokens: int = 350,
) -> MagicMock:
    """Gemini SDK の GenerateContentResponse 風の MagicMock を生成。"""
    response = MagicMock()
    if text_payload is not None:
        response.text = text_payload
    else:
        response.text = json.dumps(json_payload or {"items": []})
    usage = MagicMock()
    usage.prompt_token_count = prompt_tokens
    usage.candidates_token_count = candidates_tokens
    response.usage_metadata = usage
    return response


def _install_fake_genai_module(response: MagicMock) -> MagicMock:
    """`google.generativeai` を _GENAI_CACHE に直接 inject。"""
    genai = MagicMock()
    genai.configure = MagicMock()
    model = MagicMock()
    # 同期版 / async 版両対応
    model.generate_content = MagicMock(return_value=response)
    model.generate_content_async = AsyncMock(return_value=response)
    genai.GenerativeModel = MagicMock(return_value=model)
    inventory_parser_llm._GENAI_CACHE["module"] = genai
    return genai


@pytest.fixture(autouse=True)
def reset_genai_cache():
    """各テストで _GENAI_CACHE をクリア (テスト間の漏れ防止)。"""
    inventory_parser_llm._GENAI_CACHE.clear()
    yield
    inventory_parser_llm._GENAI_CACHE.clear()


@pytest.fixture(autouse=True)
def set_api_key(monkeypatch):
    """デフォルトで GEMINI_API_KEY を設定 (AC4.5 テストで個別に解除)。"""
    monkeypatch.setenv("GEMINI_API_KEY", "test-key-for-mocked-sdk")
    yield


# ---------------------------------------------------------------------------
# AC4.5: API キー欠落 / 不正
# ---------------------------------------------------------------------------


class TestApiKeyMissing:
    @pytest.mark.asyncio
    async def test_empty_api_key_raises_config_error(self, monkeypatch) -> None:
        monkeypatch.delenv("GEMINI_API_KEY", raising=False)
        with pytest.raises(LLMConfigError, match="GEMINI_API_KEY"):
            await parse_with_gemini(
                unparsed_lines=[{"line_no": 1, "raw_line": "テスト"}],
                knowledge_snapshot=[],
            )

    @pytest.mark.asyncio
    async def test_whitespace_only_api_key_treated_as_missing(self, monkeypatch) -> None:
        monkeypatch.setenv("GEMINI_API_KEY", "   ")
        with pytest.raises(LLMConfigError):
            await parse_with_gemini(
                unparsed_lines=[{"line_no": 1, "raw_line": "テスト"}],
                knowledge_snapshot=[],
            )


# ---------------------------------------------------------------------------
# AC4.1: Gemini を 1 回呼ぶ + items[] にマージ
# ---------------------------------------------------------------------------


class TestParseWithGeminiBasic:
    @pytest.mark.asyncio
    async def test_empty_unparsed_lines_returns_empty(self) -> None:
        result = await parse_with_gemini(unparsed_lines=[], knowledge_snapshot=[])
        assert result.items == []
        assert result.input_tokens == 0
        assert result.output_tokens == 0

    @pytest.mark.asyncio
    async def test_single_unparsed_line_returns_one_item(self) -> None:
        response = _make_fake_response(
            json_payload={
                "items": [
                    {
                        "raw_line": "リザードンex SAR 3box @8000",
                        "line_no": 1,
                        "name": "リザードンex SAR",
                        "quantity": 3,
                        "unit": "box",
                        "unit_price": 8000,
                        "condition": "new",
                        "confidence": 0.92,
                    }
                ]
            }
        )
        _install_fake_genai_module(response)

        result = await parse_with_gemini(
            unparsed_lines=[{"line_no": 1, "raw_line": "リザードンex SAR 3box @8000"}],
            knowledge_snapshot=[
                {"pattern": "リザex", "normalized_to": "リザードンex", "category": "alias"}
            ],
        )
        assert len(result.items) == 1
        item = result.items[0]
        assert isinstance(item, LLMParsedItem)
        assert item.name == "リザードンex SAR"
        assert item.quantity == 3
        assert item.unit == "box"
        assert item.unit_price == 8000.0
        assert item.line_no == 1
        # AC4.2: token 数が記録される
        assert result.input_tokens == 1200
        assert result.output_tokens == 350

    @pytest.mark.asyncio
    async def test_multiple_items_from_single_line(self) -> None:
        response = _make_fake_response(
            json_payload={
                "items": [
                    {
                        "raw_line": "リザード 3box / ピカ 2box",
                        "line_no": 1,
                        "name": "リザード",
                        "quantity": 3,
                        "unit": "box",
                    },
                    {
                        "raw_line": "リザード 3box / ピカ 2box",
                        "line_no": 1,
                        "name": "ピカチュウ",
                        "quantity": 2,
                        "unit": "box",
                    },
                ]
            }
        )
        _install_fake_genai_module(response)

        result = await parse_with_gemini(
            unparsed_lines=[{"line_no": 1, "raw_line": "リザード 3box / ピカ 2box"}],
            knowledge_snapshot=[],
        )
        assert len(result.items) == 2
        assert {it.name for it in result.items} == {"リザード", "ピカチュウ"}


# ---------------------------------------------------------------------------
# AC4.2: usage_metadata からの token 数記録
# ---------------------------------------------------------------------------


class TestTokenUsageMetadata:
    @pytest.mark.asyncio
    async def test_token_counts_extracted_from_usage_metadata(self) -> None:
        response = _make_fake_response(
            json_payload={"items": []},
            prompt_tokens=3456,
            candidates_tokens=789,
        )
        _install_fake_genai_module(response)
        result = await parse_with_gemini(
            unparsed_lines=[{"line_no": 1, "raw_line": "x"}],
            knowledge_snapshot=[],
        )
        assert result.input_tokens == 3456
        assert result.output_tokens == 789

    @pytest.mark.asyncio
    async def test_missing_usage_metadata_defaults_to_zero(self) -> None:
        response = _make_fake_response(json_payload={"items": []})
        # usage_metadata を None にして欠落シミュレート
        response.usage_metadata = None
        _install_fake_genai_module(response)
        result = await parse_with_gemini(
            unparsed_lines=[{"line_no": 1, "raw_line": "x"}],
            knowledge_snapshot=[],
        )
        assert result.input_tokens == 0
        assert result.output_tokens == 0


# ---------------------------------------------------------------------------
# Error / malformed response handling
# ---------------------------------------------------------------------------


class TestMalformedResponse:
    @pytest.mark.asyncio
    async def test_empty_response_text_raises(self) -> None:
        response = _make_fake_response(text_payload="")
        _install_fake_genai_module(response)
        with pytest.raises(LLMParseError, match="応答が空"):
            await parse_with_gemini(
                unparsed_lines=[{"line_no": 1, "raw_line": "x"}],
                knowledge_snapshot=[],
            )

    @pytest.mark.asyncio
    async def test_non_json_response_raises(self) -> None:
        response = _make_fake_response(text_payload="not json garbage")
        _install_fake_genai_module(response)
        with pytest.raises(LLMParseError, match="JSON"):
            await parse_with_gemini(
                unparsed_lines=[{"line_no": 1, "raw_line": "x"}],
                knowledge_snapshot=[],
            )

    @pytest.mark.asyncio
    async def test_items_not_array_raises(self) -> None:
        response = _make_fake_response(json_payload={"items": "not-a-list"})
        _install_fake_genai_module(response)
        with pytest.raises(LLMParseError, match="items"):
            await parse_with_gemini(
                unparsed_lines=[{"line_no": 1, "raw_line": "x"}],
                knowledge_snapshot=[],
            )

    @pytest.mark.asyncio
    async def test_items_missing_required_fields_skipped(self) -> None:
        """name / line_no / raw_line のいずれか欠落の item は静かに skip。"""
        response = _make_fake_response(json_payload={
            "items": [
                {"name": "OK", "line_no": 1, "raw_line": "x", "quantity": 1},
                {"name": "missing line_no", "raw_line": "x"},  # skip
                {"line_no": 2, "raw_line": "x"},  # skip (no name)
            ]
        })
        _install_fake_genai_module(response)
        result = await parse_with_gemini(
            unparsed_lines=[{"line_no": 1, "raw_line": "x"}],
            knowledge_snapshot=[],
        )
        assert len(result.items) == 1
        assert result.items[0].name == "OK"

    @pytest.mark.asyncio
    async def test_sdk_exception_wrapped_in_llm_parse_error(self) -> None:
        """Gemini SDK が任意例外を投げたら LLMParseError に統一する (呼出側 catch 用)。"""
        genai = MagicMock()
        genai.configure = MagicMock()
        model = MagicMock()
        model.generate_content_async = AsyncMock(side_effect=RuntimeError("network down"))
        del model.generate_content  # async only
        # 上では `hasattr(model, "generate_content_async")` が True、async 経路だけ走る
        genai.GenerativeModel = MagicMock(return_value=model)
        inventory_parser_llm._GENAI_CACHE["module"] = genai

        with pytest.raises(LLMParseError, match="network down|Gemini API"):
            await parse_with_gemini(
                unparsed_lines=[{"line_no": 1, "raw_line": "x"}],
                knowledge_snapshot=[],
            )


# ---------------------------------------------------------------------------
# Output schema / prompt structure
# ---------------------------------------------------------------------------


class TestPromptAndSchema:
    @pytest.mark.asyncio
    async def test_prompt_contains_unparsed_lines(self) -> None:
        response = _make_fake_response(json_payload={"items": []})
        genai = _install_fake_genai_module(response)

        await parse_with_gemini(
            unparsed_lines=[
                {"line_no": 5, "raw_line": "ユニーク文字列ABCXYZ"},
            ],
            knowledge_snapshot=[],
        )
        # GenerativeModel が呼ばれて、generate_content_async に prompt が渡る
        model = genai.GenerativeModel.return_value
        # async 版が優先される
        assert model.generate_content_async.await_count == 1
        passed_prompt = model.generate_content_async.await_args.args[0]
        assert "ユニークーー" not in passed_prompt  # sanity check
        assert "ユニーク文字列ABCXYZ" in passed_prompt
        assert "L5:" in passed_prompt  # line_no が prompt に入る

    @pytest.mark.asyncio
    async def test_supplier_prompt_used_as_instruction(self) -> None:
        # ADR-085: supplier_prompt 指定時はそれを解析指針の本体に使い、
        # 出力は JSON 強制（response_schema）を保つ。
        response = _make_fake_response(json_payload={"items": []})
        genai = _install_fake_genai_module(response)
        await parse_with_gemini(
            unparsed_lines=[{"line_no": 1, "raw_line": "■商品A 3点 @1000"}],
            knowledge_snapshot=[],
            supplier_prompt="# 役割\nシンソク形式を解析せよ。UNIQUE_SUPPLIER_MARKER_777",
        )
        model = genai.GenerativeModel.return_value
        prompt = model.generate_content_async.await_args.args[0]
        assert "UNIQUE_SUPPLIER_MARKER_777" in prompt  # 仕入先プロンプト本文が指針に入る
        assert '"items"' in prompt  # JSON 出力指示が入る
        assert "■商品A 3点 @1000" in prompt  # 入力行も含まれる

    @pytest.mark.asyncio
    async def test_generation_config_uses_structured_output(self) -> None:
        response = _make_fake_response(json_payload={"items": []})
        genai = _install_fake_genai_module(response)
        await parse_with_gemini(
            unparsed_lines=[{"line_no": 1, "raw_line": "x"}],
            knowledge_snapshot=[],
        )
        # GenerativeModel(model_name=..., generation_config=...)
        kwargs = genai.GenerativeModel.call_args.kwargs
        gen_cfg = kwargs.get("generation_config", {})
        assert gen_cfg.get("response_mime_type") == "application/json"
        assert "response_schema" in gen_cfg
        schema = gen_cfg["response_schema"]
        assert schema["type"] == "object"
        assert "items" in schema["properties"]

    @pytest.mark.asyncio
    async def test_uses_gemini_2_5_flash_by_default(self) -> None:
        response = _make_fake_response(json_payload={"items": []})
        genai = _install_fake_genai_module(response)
        await parse_with_gemini(
            unparsed_lines=[{"line_no": 1, "raw_line": "x"}],
            knowledge_snapshot=[],
        )
        kwargs = genai.GenerativeModel.call_args.kwargs
        assert kwargs.get("model_name") == "gemini-2.5-flash"

    @pytest.mark.asyncio
    async def test_knowledge_snapshot_top30_included(self) -> None:
        response = _make_fake_response(json_payload={"items": []})
        genai = _install_fake_genai_module(response)
        snapshot = [
            {"pattern": f"alias_{i}", "normalized_to": f"norm_{i}", "category": "alias"}
            for i in range(50)
        ]
        await parse_with_gemini(
            unparsed_lines=[{"line_no": 1, "raw_line": "x"}],
            knowledge_snapshot=snapshot,
        )
        model = genai.GenerativeModel.return_value
        prompt = model.generate_content_async.await_args.args[0]
        # 上位 30 件を含む
        assert "alias_0" in prompt
        assert "alias_29" in prompt
        # 31 件目以降は含まれない (cost 抑制)
        assert "alias_45" not in prompt


# ---------------------------------------------------------------------------
# Hybrid integration: parse_inventory_message が rule_v1 + LLM をマージする
# ---------------------------------------------------------------------------


class TestHybridParseInventoryMessage:
    """parse_inventory_message hybrid 経路の挙動を、rule_v1 結果 + LLM mock で検証。"""

    @pytest.mark.asyncio
    async def test_tenant_id_none_skips_llm_call(self) -> None:
        """tenant_id 未指定なら LLM を一切呼ばず rule_v1 結果のみ返す (Sprint 3 互換)。"""
        from app.services.inventory_parser import (
            ParseResult,
            UnparsedLine,
            parse_inventory_message,
        )

        db = AsyncMock()
        # _load_aliases_for_supplier / _load_active_rules / parse_raw_content の代わりに
        # parse_inventory_message を patch して挙動を絞る方が確実
        with patch(
            "app.services.inventory_parser._load_aliases_for_supplier",
            new=AsyncMock(return_value=[]),
        ), patch(
            "app.services.inventory_parser._load_active_rules",
            new=AsyncMock(return_value=[]),
        ), patch(
            "app.services.inventory_parser._load_supplier_prompt",
            new=AsyncMock(return_value=None),
        ), patch(
            "app.services.inventory_parser.parse_raw_content",
            return_value=ParseResult(
                items=[],
                excludes=[],
                unparsed=[UnparsedLine(raw_line="x", line_no=1, reason="no_alias")],
                parse_engine="rule_v1",
            ),
        ):
            result = await parse_inventory_message(
                db=db, raw_content="x", supplier_id=3
            )
        assert result.parse_engine == "rule_v1"
        # unparsed が温存されている
        assert len(result.unparsed) == 1

    @pytest.mark.asyncio
    async def test_no_unparsed_skips_llm_call(self) -> None:
        """rule_v1 で完全に解けたら LLM 呼ばない。"""
        from app.services.inventory_parser import (
            ParseResult,
            parse_inventory_message,
        )

        db = AsyncMock()
        with patch(
            "app.services.inventory_parser._load_aliases_for_supplier",
            new=AsyncMock(return_value=[]),
        ), patch(
            "app.services.inventory_parser._load_active_rules",
            new=AsyncMock(return_value=[]),
        ), patch(
            "app.services.inventory_parser._load_supplier_prompt",
            new=AsyncMock(return_value=None),
        ), patch(
            "app.services.inventory_parser.parse_raw_content",
            return_value=ParseResult(
                items=[], excludes=[], unparsed=[], parse_engine="rule_v1"
            ),
        ):
            result = await parse_inventory_message(
                db=db, raw_content="x", supplier_id=3, tenant_id=6
            )
        assert result.parse_engine == "rule_v1"

    @pytest.mark.asyncio
    async def test_budget_hard_stop_blocks_llm_call(self) -> None:
        """AC4.3: hard_stop=true で予算超過 → API 呼ばず parse_engine='rule_v1_fallback_blocked'。"""
        from app.services.inventory_parser import (
            ParseResult,
            UnparsedLine,
            parse_inventory_message,
        )

        db = AsyncMock()
        with patch(
            "app.services.inventory_parser._load_aliases_for_supplier",
            new=AsyncMock(return_value=[]),
        ), patch(
            "app.services.inventory_parser._load_active_rules",
            new=AsyncMock(return_value=[]),
        ), patch(
            "app.services.inventory_parser._load_supplier_prompt",
            new=AsyncMock(return_value=None),
        ), patch(
            "app.services.inventory_parser.parse_raw_content",
            return_value=ParseResult(
                items=[],
                excludes=[],
                unparsed=[UnparsedLine(raw_line="x", line_no=1, reason="no_alias")],
                parse_engine="rule_v1",
            ),
        ), patch(
            "app.services.llm_budget.reset_monthly_if_needed",
            new=AsyncMock(return_value=False),
        ), patch(
            "app.services.llm_budget.check_budget",
            new=AsyncMock(return_value=__import__("app.services.llm_budget", fromlist=["BudgetStatus"]).BudgetStatus.HARD_STOP),
        ), patch(
            "app.services.llm_budget.get_budget_snapshot",
            new=AsyncMock(return_value=None),  # notify_admin スキップ
        ), patch(
            "app.services.inventory_parser_llm.parse_with_gemini",
            new=AsyncMock(),
        ) as mock_gemini:
            result = await parse_inventory_message(
                db=db, raw_content="x", supplier_id=3, tenant_id=6
            )
        assert result.parse_engine == "rule_v1_fallback_blocked"
        # API は呼ばれていない (AC4.3 重要)
        mock_gemini.assert_not_called()

    @pytest.mark.asyncio
    async def test_llm_config_error_degrades_to_rule_v1(self) -> None:
        """AC4.5: GEMINI_API_KEY 不在で LLMConfigError → parse_engine='rule_v1' 維持。"""
        from app.services.inventory_parser import (
            ParseResult,
            UnparsedLine,
            parse_inventory_message,
        )
        from app.services.inventory_parser_llm import LLMConfigError
        from app.services.llm_budget import BudgetStatus

        db = AsyncMock()
        with patch(
            "app.services.inventory_parser._load_aliases_for_supplier",
            new=AsyncMock(return_value=[]),
        ), patch(
            "app.services.inventory_parser._load_active_rules",
            new=AsyncMock(return_value=[]),
        ), patch(
            "app.services.inventory_parser._load_supplier_prompt",
            new=AsyncMock(return_value=None),
        ), patch(
            "app.services.inventory_parser.parse_raw_content",
            return_value=ParseResult(
                items=[],
                excludes=[],
                unparsed=[UnparsedLine(raw_line="x", line_no=1, reason="no_alias")],
                parse_engine="rule_v1",
            ),
        ), patch(
            "app.services.llm_budget.reset_monthly_if_needed",
            new=AsyncMock(return_value=False),
        ), patch(
            "app.services.llm_budget.check_budget",
            new=AsyncMock(return_value=BudgetStatus.UNDER),
        ), patch(
            "app.services.inventory_parser_llm.parse_with_gemini",
            new=AsyncMock(side_effect=LLMConfigError("no key")),
        ):
            result = await parse_inventory_message(
                db=db, raw_content="x", supplier_id=3, tenant_id=6
            )
        # 500 を投げない、rule_v1 のまま、unparsed は温存
        assert result.parse_engine == "rule_v1"
        assert len(result.unparsed) == 1

    @pytest.mark.asyncio
    async def test_llm_api_error_degrades_to_rule_v1(self) -> None:
        """AC4.5: API 失敗時も graceful degrade。"""
        from app.services.inventory_parser import (
            ParseResult,
            UnparsedLine,
            parse_inventory_message,
        )
        from app.services.inventory_parser_llm import LLMParseError
        from app.services.llm_budget import BudgetStatus

        db = AsyncMock()
        with patch(
            "app.services.inventory_parser._load_aliases_for_supplier",
            new=AsyncMock(return_value=[]),
        ), patch(
            "app.services.inventory_parser._load_active_rules",
            new=AsyncMock(return_value=[]),
        ), patch(
            "app.services.inventory_parser._load_supplier_prompt",
            new=AsyncMock(return_value=None),
        ), patch(
            "app.services.inventory_parser.parse_raw_content",
            return_value=ParseResult(
                items=[],
                excludes=[],
                unparsed=[UnparsedLine(raw_line="x", line_no=1, reason="no_alias")],
                parse_engine="rule_v1",
            ),
        ), patch(
            "app.services.llm_budget.reset_monthly_if_needed",
            new=AsyncMock(return_value=False),
        ), patch(
            "app.services.llm_budget.check_budget",
            new=AsyncMock(return_value=BudgetStatus.UNDER),
        ), patch(
            "app.services.inventory_parser_llm.parse_with_gemini",
            new=AsyncMock(side_effect=LLMParseError("API 500")),
        ):
            result = await parse_inventory_message(
                db=db, raw_content="x", supplier_id=3, tenant_id=6
            )
        assert result.parse_engine == "rule_v1"

    @pytest.mark.asyncio
    async def test_successful_hybrid_merges_items_and_clears_unparsed(self) -> None:
        """LLM 成功 → items[] に追加、unparsed から該当 line_no 削除、
        parse_engine='hybrid_rule_v1_llm_v1'、record_cost が呼ばれる。"""
        from app.services.inventory_parser import (
            ParseResult,
            UnparsedLine,
            parse_inventory_message,
        )
        from app.services.inventory_parser_llm import LLMParsedItem, LLMParseResult
        from app.services.llm_budget import BudgetStatus

        db = AsyncMock()
        mock_record_cost = AsyncMock(return_value=Decimal("0.0004"))

        with patch(
            "app.services.inventory_parser._load_aliases_for_supplier",
            new=AsyncMock(return_value=[]),
        ), patch(
            "app.services.inventory_parser._load_active_rules",
            new=AsyncMock(return_value=[]),
        ), patch(
            "app.services.inventory_parser._load_supplier_prompt",
            new=AsyncMock(return_value=None),
        ), patch(
            "app.services.inventory_parser.parse_raw_content",
            return_value=ParseResult(
                items=[],
                excludes=[],
                unparsed=[
                    UnparsedLine(raw_line="リザex 3", line_no=1, reason="no_alias"),
                    UnparsedLine(raw_line="ピカ 5", line_no=2, reason="no_alias"),
                ],
                parse_engine="rule_v1",
            ),
        ), patch(
            "app.services.llm_budget.reset_monthly_if_needed",
            new=AsyncMock(return_value=False),
        ), patch(
            "app.services.llm_budget.check_budget",
            new=AsyncMock(return_value=BudgetStatus.UNDER),
        ), patch(
            "app.services.llm_budget.record_cost", new=mock_record_cost,
        ), patch(
            "app.services.inventory_parser_llm.parse_with_gemini",
            new=AsyncMock(
                return_value=LLMParseResult(
                    items=[
                        LLMParsedItem(
                            raw_line="リザex 3",
                            line_no=1,
                            name="リザードンex",
                            quantity=3,
                            unit="box",
                            unit_price=8000.0,
                            condition="new",
                            confidence=0.9,
                        )
                    ],
                    input_tokens=1200,
                    output_tokens=350,
                    model="gemini-2.5-flash",
                )
            ),
        ):
            result = await parse_inventory_message(
                db=db, raw_content="x", supplier_id=3, tenant_id=6
            )
        assert result.parse_engine == "hybrid_rule_v1_llm_v1"
        # LLM 由来 item が 1 件追加
        assert len(result.items) == 1
        assert result.items[0].product_name == "リザードンex"
        assert result.items[0].quantity == 3
        # line_no=1 の unparsed は削除、line_no=2 は残存
        assert len(result.unparsed) == 1
        assert result.unparsed[0].line_no == 2
        # AC4.2: record_cost が token 数で呼ばれている
        mock_record_cost.assert_awaited_once()
        # 第 2 引数 = tenant_id (db, tenant_id, **kwargs)
        call = mock_record_cost.await_args
        assert call.args[1] == 6
        assert call.kwargs["input_tokens"] == 1200
        assert call.kwargs["output_tokens"] == 350

    @pytest.mark.asyncio
    async def test_reset_monthly_called_before_check(self) -> None:
        """AC4.4: parse 冒頭で reset_monthly_if_needed が呼ばれる。"""
        from app.services.inventory_parser import (
            ParseResult,
            UnparsedLine,
            parse_inventory_message,
        )
        from app.services.llm_budget import BudgetStatus

        db = AsyncMock()
        mock_reset = AsyncMock(return_value=True)

        with patch(
            "app.services.inventory_parser._load_aliases_for_supplier",
            new=AsyncMock(return_value=[]),
        ), patch(
            "app.services.inventory_parser._load_active_rules",
            new=AsyncMock(return_value=[]),
        ), patch(
            "app.services.inventory_parser._load_supplier_prompt",
            new=AsyncMock(return_value=None),
        ), patch(
            "app.services.inventory_parser.parse_raw_content",
            return_value=ParseResult(
                items=[],
                excludes=[],
                unparsed=[UnparsedLine(raw_line="x", line_no=1, reason="no_alias")],
                parse_engine="rule_v1",
            ),
        ), patch(
            "app.services.llm_budget.reset_monthly_if_needed", new=mock_reset,
        ), patch(
            "app.services.llm_budget.check_budget",
            new=AsyncMock(return_value=BudgetStatus.NO_BUDGET_ROW),
        ):
            await parse_inventory_message(
                db=db, raw_content="x", supplier_id=3, tenant_id=6
            )
        mock_reset.assert_awaited_once()
        # tenant_id=6 で呼ばれていること
        call_args = mock_reset.await_args
        assert call_args.args[1] == 6 or call_args.kwargs.get("tenant_id") == 6

    @pytest.mark.asyncio
    async def test_no_budget_row_blocks_without_notification(self) -> None:
        """budget 行が存在しない tenant → NO_BUDGET_ROW で API 呼ばない、通知も飛ばない。"""
        from app.services.inventory_parser import (
            ParseResult,
            UnparsedLine,
            parse_inventory_message,
        )
        from app.services.llm_budget import BudgetStatus

        db = AsyncMock()
        mock_notify = AsyncMock()
        mock_gemini = AsyncMock()

        with patch(
            "app.services.inventory_parser._load_aliases_for_supplier",
            new=AsyncMock(return_value=[]),
        ), patch(
            "app.services.inventory_parser._load_active_rules",
            new=AsyncMock(return_value=[]),
        ), patch(
            "app.services.inventory_parser._load_supplier_prompt",
            new=AsyncMock(return_value=None),
        ), patch(
            "app.services.inventory_parser.parse_raw_content",
            return_value=ParseResult(
                items=[],
                excludes=[],
                unparsed=[UnparsedLine(raw_line="x", line_no=1, reason="no_alias")],
                parse_engine="rule_v1",
            ),
        ), patch(
            "app.services.llm_budget.reset_monthly_if_needed",
            new=AsyncMock(return_value=False),
        ), patch(
            "app.services.llm_budget.check_budget",
            new=AsyncMock(return_value=BudgetStatus.NO_BUDGET_ROW),
        ), patch(
            "app.services.discord_notifier.notify_budget_exhausted", new=mock_notify,
        ), patch(
            "app.services.inventory_parser_llm.parse_with_gemini", new=mock_gemini,
        ):
            result = await parse_inventory_message(
                db=db, raw_content="x", supplier_id=3, tenant_id=999
            )
        assert result.parse_engine == "rule_v1_fallback_blocked"
        mock_gemini.assert_not_called()
        # NO_BUDGET_ROW では通知も飛ばない
        mock_notify.assert_not_called()
