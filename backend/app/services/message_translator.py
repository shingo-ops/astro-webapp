from __future__ import annotations

"""
ADR-088: 受信箱メッセージ AI 翻訳サービス。

inventory_parser_llm.py のパターンを踏襲:
  - lazy SDK init / _ensure_api_key / LLMConfigError / LLMParseError 例外
  - llm_budget.check_budget() を API 呼び出し前に実行
  - llm_budget.record_cost() を API 呼び出し後に実行
  - DB キャッシュ確認 → ヒットなら cached: true で即返却
  - モデル: gemini-2.5-flash 固定
"""

import logging
import os
from dataclasses import dataclass
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.inventory_parser_llm import (
    LLMConfigError,
    LLMParseError,
)
from app.services.llm_budget import BudgetStatus, check_budget, record_cost

logger = logging.getLogger(__name__)

MODEL_NAME = "gemini-2.5-flash"


# ---------------------------------------------------------------------------
# Public types
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class TranslationResult:
    """translate_message() の戻り値。"""

    translated_text: str
    cached: bool
    engine: str


# ---------------------------------------------------------------------------
# Gemini SDK lazy initialization (inventory_parser_llm パターン踏襲)
# ---------------------------------------------------------------------------

_GENAI_CACHE: dict[str, Any] = {}


def _get_genai_module() -> Any:
    """`google.generativeai` を遅延 import。"""
    if "module" not in _GENAI_CACHE:
        try:
            import google.generativeai as genai  # type: ignore[import-untyped]
        except ImportError as exc:
            raise LLMConfigError(
                "google-generativeai がインストールされていません。"
            ) from exc
        _GENAI_CACHE["module"] = genai
    return _GENAI_CACHE["module"]


def _ensure_api_key() -> str:
    """env から GEMINI_API_KEY を取得。未設定なら LLMConfigError。"""
    key = os.getenv("GEMINI_API_KEY", "").strip()
    if not key:
        raise LLMConfigError(
            "GEMINI_API_KEY が未設定です。翻訳機能は無効化されます。"
        )
    return key


# ---------------------------------------------------------------------------
# DB cache
# ---------------------------------------------------------------------------


async def _get_cached_translation(
    db: AsyncSession,
    table_ref: str,
    message_id: str,
    target_language: str,
) -> str | None:
    """DB キャッシュから翻訳テキストを取得。見つからなければ None。"""
    result = await db.execute(
        text(
            f"SELECT translated_text FROM {table_ref} "
            "WHERE message_id = :message_id AND target_language = :target_language"
        ),
        {"message_id": message_id, "target_language": target_language},
    )
    row = result.first()
    if row:
        return str(row[0])
    return None


async def _save_translation(
    db: AsyncSession,
    table_ref: str,
    message_id: str,
    target_language: str,
    translated_text: str,
    engine: str,
) -> None:
    """翻訳結果を DB キャッシュに保存 (ON CONFLICT で冪等)。"""
    await db.execute(
        text(
            f"INSERT INTO {table_ref} (message_id, target_language, translated_text, engine) "
            "VALUES (:message_id, :target_language, :translated_text, :engine) "
            "ON CONFLICT (message_id, target_language) DO UPDATE "
            "SET translated_text = :translated_text, engine = :engine"
        ),
        {
            "message_id": message_id,
            "target_language": target_language,
            "translated_text": translated_text,
            "engine": engine,
        },
    )


# ---------------------------------------------------------------------------
# Gemini API call
# ---------------------------------------------------------------------------


def _build_prompt(message_text: str, target_language: str) -> str:
    """翻訳プロンプトを構築。"""
    return (
        f"You are a professional translator. Translate the following message to {target_language}.\n"
        "Preserve the tone and nuance. Return only the translated text, nothing else.\n"
        f"Message: {message_text}"
    )


async def _call_gemini(prompt: str) -> tuple[str, int, int]:
    """Gemini API を呼び出して翻訳テキストと token 使用量を返す。

    Returns:
        (translated_text, input_tokens, output_tokens)
    """
    api_key = _ensure_api_key()
    genai = _get_genai_module()
    genai.configure(api_key=api_key)

    generation_config = {
        "temperature": 0.1,
    }

    try:
        model = genai.GenerativeModel(
            model_name=MODEL_NAME,
            generation_config=generation_config,
        )
        # async 対応
        if hasattr(model, "generate_content_async"):
            response = await model.generate_content_async(prompt)
        else:
            import asyncio
            loop = asyncio.get_running_loop()
            response = await loop.run_in_executor(
                None, model.generate_content, prompt
            )
    except Exception as exc:
        logger.exception("[message_translator] Gemini call failed: %s", exc)
        raise LLMParseError(f"Gemini API 呼び出し失敗: {exc}") from exc

    text_payload = getattr(response, "text", "") or ""
    if not text_payload:
        raise LLMParseError("Gemini 応答が空でした")

    usage = getattr(response, "usage_metadata", None)
    input_tokens = int(getattr(usage, "prompt_token_count", 0) or 0)
    output_tokens = int(getattr(usage, "candidates_token_count", 0) or 0)

    return text_payload.strip(), input_tokens, output_tokens


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


async def translate_message(
    db: AsyncSession,
    tenant_id: int,
    table_ref: str,
    message_id: str,
    message_text: str,
    target_language: str,
) -> TranslationResult:
    """メッセージを翻訳する。キャッシュヒット時は Gemini を呼ばない。

    Args:
        db: DB session
        tenant_id: テナント ID (budget 管理用)
        table_ref: tenant-prefixed table reference for message_translations
        message_id: 翻訳対象メッセージの ID (meta_messages.message_id)
        message_text: 翻訳対象のテキスト
        target_language: 翻訳先言語 (e.g. "ja", "en")

    Returns:
        TranslationResult

    Raises:
        LLMConfigError: API key 未設定
        LLMParseError: Gemini API 呼び出し失敗
    """
    # 1. DB キャッシュ確認
    cached_text = await _get_cached_translation(
        db, table_ref, message_id, target_language
    )
    if cached_text is not None:
        logger.info(
            "[message_translator] cache hit: message_id=%s lang=%s",
            message_id,
            target_language,
        )
        return TranslationResult(
            translated_text=cached_text,
            cached=True,
            engine=MODEL_NAME,
        )

    # 2. Budget チェック
    budget_status = await check_budget(db, tenant_id)
    if budget_status in (BudgetStatus.HARD_STOP, BudgetStatus.NO_BUDGET_ROW):
        raise BudgetExceededError(budget_status)

    # 3. Gemini 呼び出し
    prompt = _build_prompt(message_text, target_language)
    translated_text, input_tokens, output_tokens = await _call_gemini(prompt)

    # 4. コスト記録
    await record_cost(
        db, tenant_id, input_tokens, output_tokens, model=MODEL_NAME
    )

    # 5. DB キャッシュ保存
    await _save_translation(
        db, table_ref, message_id, target_language, translated_text, MODEL_NAME
    )

    await db.commit()

    logger.info(
        "[message_translator] translated: message_id=%s lang=%s in_tokens=%s out_tokens=%s",
        message_id,
        target_language,
        input_tokens,
        output_tokens,
    )
    return TranslationResult(
        translated_text=translated_text,
        cached=False,
        engine=MODEL_NAME,
    )


# ---------------------------------------------------------------------------
# Custom exceptions
# ---------------------------------------------------------------------------


class BudgetExceededError(Exception):
    """LLM 予算超過エラー。"""

    def __init__(self, status: BudgetStatus):
        self.status = status
        super().__init__(f"LLM budget exceeded: {status.value}")


__all__ = [
    "BudgetExceededError",
    "TranslationResult",
    "translate_message",
]
