from __future__ import annotations

"""
Fernet による対称鍵暗号化サービス（Phase 1-D）。

主な用途:
  - Meta Page Access Token の暗号化保存（`tenant_meta_config.page_access_token_encrypted`）
  - 将来的な秘密情報（Bot Token、API キー等）の暗号化保存

たとえ話:
  「鍵付きの金庫」。鍵（METADATA_FERNET_KEY）を持つ人だけが
  中の書類（生トークン）を読み書きできる。
  鍵を紛失すると永遠に金庫を開けられなくなるので、
  Bitwarden 等で鍵を厳重に保管する運用が必須。

設計判断:
  - cryptography.fernet.Fernet を直接ラップ（業界標準、AES-128-CBC + HMAC-SHA256）
  - 鍵は環境変数 `METADATA_FERNET_KEY`（urlsafe base64 32 bytes）から取得
  - encrypt/decrypt は文字列 ↔ 文字列で扱う（DB 側は BYTEA で保存するが、
    本サービスは文字列 API のみ。BYTEA 変換は呼び出し側の責務）
  - Fernet は内部でバージョニング・タイムスタンプ・HMAC を含むため、
    将来の鍵ローテーションや TTL 検証もこのレイヤで拡張可能

エラー方針:
  - 鍵未設定: `EncryptionConfigurationError`（FastAPI startup や CLI で早期検知）
  - 復号失敗（不正キー、改ざん、破損）: `EncryptionError`
  - 平文 None / 非文字列: `TypeError`

変更履歴:
  2026-04-30: Phase 1-D Sprint 1 初版（しんごさん依頼）
"""

import os
from functools import lru_cache
from typing import Optional

from cryptography.fernet import Fernet, InvalidToken


_ENV_KEY = "METADATA_FERNET_KEY"


class EncryptionConfigurationError(RuntimeError):
    """`METADATA_FERNET_KEY` 環境変数が未設定 / 形式不正のとき投げる。"""


class EncryptionError(RuntimeError):
    """暗号化・復号の処理失敗（鍵不一致、改ざん、形式不正など）。"""


def _load_key_from_env(env_name: str = _ENV_KEY) -> bytes:
    """環境変数から Fernet 鍵を bytes として読み込む。

    Fernet 鍵は urlsafe base64 32 bytes（= 44 文字、末尾 `=` 含む）。
    生成方法:
        python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
    """
    raw = os.getenv(env_name)
    if not raw:
        raise EncryptionConfigurationError(
            f"環境変数 {env_name} が設定されていません。"
            f"`python -c \"from cryptography.fernet import Fernet; "
            f"print(Fernet.generate_key().decode())\"` で生成して設定してください。"
        )
    # Fernet は str/bytes どちらも受けるが、形式不正は __init__ で ValueError を出す
    try:
        # 形式検証のため一度 Fernet を作ってみる（インスタンスは捨てる）
        Fernet(raw.encode("ascii"))
    except (ValueError, TypeError) as e:
        raise EncryptionConfigurationError(
            f"環境変数 {env_name} の値が Fernet 鍵として不正です（urlsafe base64 32 bytes 必須）: {e}"
        ) from e
    return raw.encode("ascii")


@lru_cache(maxsize=1)
def _get_default_fernet() -> Fernet:
    """環境変数から鍵を読み込んで Fernet インスタンスを返す（プロセス内キャッシュ）。

    `lru_cache` を使うことで:
      - 環境変数 read を 1 度だけにし、リクエスト毎の I/O を回避
      - テスト時は `_get_default_fernet.cache_clear()` でリセット可能
    """
    return Fernet(_load_key_from_env())


def reset_cache() -> None:
    """テスト用: 環境変数を切り替えた後に内部キャッシュをクリアする。"""
    _get_default_fernet.cache_clear()


def encrypt(plaintext: str, *, fernet: Optional[Fernet] = None) -> str:
    """平文を暗号化して urlsafe base64 文字列で返す。

    Args:
        plaintext: 暗号化対象の文字列（空文字も OK、None は TypeError）
        fernet: テスト用に Fernet インスタンスを差し替えたいときに使用

    Returns:
        Fernet ciphertext（urlsafe base64、文字列）

    Raises:
        TypeError: plaintext が文字列でない
        EncryptionConfigurationError: 鍵未設定
    """
    if not isinstance(plaintext, str):
        raise TypeError(f"plaintext must be str, got {type(plaintext).__name__}")
    f = fernet if fernet is not None else _get_default_fernet()
    token = f.encrypt(plaintext.encode("utf-8"))
    return token.decode("ascii")


def decrypt(ciphertext: str, *, fernet: Optional[Fernet] = None) -> str:
    """Fernet ciphertext を復号して平文を返す。

    Args:
        ciphertext: encrypt() が返した文字列（または同じ鍵で生成された Fernet token）
        fernet: テスト用差し替え

    Returns:
        平文（utf-8 文字列）

    Raises:
        TypeError: ciphertext が文字列でない
        EncryptionConfigurationError: 鍵未設定
        EncryptionError: 鍵不一致 / 改ざん / 形式不正で復号失敗
    """
    if not isinstance(ciphertext, str):
        raise TypeError(f"ciphertext must be str, got {type(ciphertext).__name__}")
    f = fernet if fernet is not None else _get_default_fernet()
    try:
        plaintext_bytes = f.decrypt(ciphertext.encode("ascii"))
    except InvalidToken as e:
        # InvalidToken は鍵不一致 / 改ざん / フォーマット不正のいずれか
        raise EncryptionError("ciphertext の復号に失敗しました（鍵不一致または破損）") from e
    return plaintext_bytes.decode("utf-8")


__all__ = [
    "EncryptionConfigurationError",
    "EncryptionError",
    "encrypt",
    "decrypt",
    "reset_cache",
]
