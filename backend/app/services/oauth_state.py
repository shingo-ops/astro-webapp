from __future__ import annotations

"""
OAuth state ストレージ（Phase 1-D Sprint 2）。

Facebook OAuth の CSRF 対策として、`/meta/connect/start` で発行した state を
Redis に 10 分 TTL で保存し、`/meta/connect/callback` で参照 + 削除する。
state 文字列は `secrets.token_urlsafe(32)` で生成（推測不可能）し、Redis に
保存する payload は Fernet で暗号化する（Redis に PII / 内部情報を平文で残さない）。

たとえ話:
  「銀行のワンタイムパスワード」。
  - 連携開始時に 1 度だけ使えるパスワード（state）を発行
  - Meta から戻って来たときに「同じパスワードか？」を確認し、
    確認後すぐに使い捨てる（再利用防止）
  - パスワードに紐づく注文書（tenant_id, staff_id）は金庫に暗号化保存

設計判断:
  - state 自体は URL-safe な乱数（推測不可能、署名検証不要）
  - Redis key: `meta_oauth_state:<state>` で 10 分 TTL
  - value: {tenant_id, staff_id, created_at, nonce} を JSON 化 → Fernet 暗号化 → 文字列化
  - validate(state) は GETDEL 相当の "取り出して即削除"（再利用防止）
  - Redis 未接続なら start は失敗、validate は False（fail-closed）

参考: spec §6-1
"""

import json
import logging
import secrets
from datetime import datetime, timezone
from typing import Optional

from app.cache import get_redis
from app.services import encryption

logger = logging.getLogger(__name__)


_REDIS_KEY_PREFIX = "meta_oauth_state:"
_DEFAULT_TTL_SECONDS = 600  # 10 分


class OAuthStateError(RuntimeError):
    """state 発行 / 検証で起きる業務例外。"""


def _redis_key(state: str) -> str:
    return f"{_REDIS_KEY_PREFIX}{state}"


def generate_state() -> str:
    """推測不可能な OAuth state 文字列を返す。

    `secrets.token_urlsafe(32)` は 32 bytes（≒256 bit）のランダム値を base64url で
    エンコードし、43 文字程度になる。Meta の state 上限は十分長く取れる。
    """
    return secrets.token_urlsafe(32)


async def issue_state(
    tenant_id: int,
    staff_id: int,
    *,
    ttl_seconds: int = _DEFAULT_TTL_SECONDS,
) -> dict[str, object]:
    """state を新規発行し、Redis に Fernet 暗号化したペイロードを TTL 付きで保存する。

    Args:
        tenant_id: 接続を開始したテナント ID
        staff_id: 開始した staff の ID（監査用）
        ttl_seconds: state の有効期間（既定 600 秒）

    Returns:
        {
          "state": "<urlsafe-random-string>",
          "expires_at": "<ISO 8601 UTC>",
          "ttl_seconds": 600,
        }

    Raises:
        OAuthStateError: Redis 未接続 / 書き込み失敗
    """
    if tenant_id is None or staff_id is None:
        raise ValueError("tenant_id and staff_id are required")
    if ttl_seconds <= 0:
        raise ValueError("ttl_seconds must be positive")

    r = get_redis()
    if r is None:
        raise OAuthStateError(
            "Redis 未接続のため OAuth state を発行できません。Redis を起動してください"
        )

    state = generate_state()
    nonce = secrets.token_hex(8)
    now = datetime.now(timezone.utc)
    payload = {
        "tenant_id": int(tenant_id),
        "staff_id": int(staff_id),
        "created_at": now.isoformat(),
        "nonce": nonce,
    }
    encrypted = encryption.encrypt(json.dumps(payload, separators=(",", ":")))

    try:
        await r.setex(_redis_key(state), ttl_seconds, encrypted)
    except Exception as e:  # pragma: no cover
        logger.exception("OAuth state の Redis 書き込みに失敗")
        raise OAuthStateError("OAuth state を保存できませんでした") from e

    expires_at_ts = now.timestamp() + ttl_seconds
    return {
        "state": state,
        "expires_at": datetime.fromtimestamp(expires_at_ts, tz=timezone.utc).isoformat(),
        "ttl_seconds": ttl_seconds,
    }


async def consume_state(state: str) -> Optional[dict[str, object]]:
    """state を検証して payload を返し、同時に Redis から削除する（one-time 使用）。

    再利用防止のため、検証成功後は **必ず** 削除する。Redis のパイプライン
    （GET + DEL）を atomic に実行することで、競合時の二重消費も防ぐ。

    Args:
        state: クライアントから戻って来た state 文字列

    Returns:
        ペイロード dict {tenant_id, staff_id, created_at, nonce} もしくは None。
        以下のケースで None を返す:
          - state 文字列が空
          - Redis に該当 key が無い（期限切れ or 改ざん or 既に消費済）
          - Fernet 復号失敗（鍵不一致 等）

    Raises:
        OAuthStateError: Redis 未接続またはパイプライン実行中に接続エラーが発生した場合。
    """
    if not state:
        return None

    r = get_redis()
    if r is None:
        logger.error("Redis 未接続のため OAuth state を検証できません")
        raise OAuthStateError("Redis 未接続のため OAuth state を検証できません")

    key = _redis_key(state)
    try:
        # GET と DEL を atomic に実行（pipeline transaction）
        async with r.pipeline(transaction=True) as pipe:
            pipe.get(key)
            pipe.delete(key)
            results = await pipe.execute()
        encrypted = results[0]
    except Exception as exc:
        logger.exception("OAuth state の Redis 取得に失敗")
        raise OAuthStateError("Redis パイプライン実行中に接続エラーが発生しました") from exc

    if not encrypted:
        return None

    try:
        plain = encryption.decrypt(encrypted)
        payload = json.loads(plain)
    except Exception:
        logger.exception("OAuth state ペイロードの復号 / parse に失敗")
        return None

    if not isinstance(payload, dict):
        return None
    if "tenant_id" not in payload or "staff_id" not in payload:
        return None
    return payload


__all__ = [
    "OAuthStateError",
    "generate_state",
    "issue_state",
    "consume_state",
]
