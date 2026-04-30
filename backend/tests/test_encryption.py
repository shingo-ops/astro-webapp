"""
Fernet 暗号化サービス（app.services.encryption）の単体テスト。

カバー範囲:
  - 環境変数 METADATA_FERNET_KEY からの鍵ロード
  - encrypt / decrypt のラウンドトリップ
  - 異なる鍵での復号失敗
  - 空文字列の往復
  - 非文字列入力の TypeError
  - 鍵未設定 / 不正形式での EncryptionConfigurationError

実行:
  pytest backend/tests/test_encryption.py -v

変更履歴:
  2026-04-30: Phase 1-D Sprint 1 初版
"""

import os

import pytest
from cryptography.fernet import Fernet

from app.services import encryption
from app.services.encryption import (
    EncryptionConfigurationError,
    EncryptionError,
    decrypt,
    encrypt,
)


@pytest.fixture(autouse=True)
def _reset_encryption_cache():
    """各テスト前後に lru_cache をクリアし、鍵環境変数の差し替えを反映できるようにする。"""
    encryption.reset_cache()
    yield
    encryption.reset_cache()


@pytest.fixture
def fernet_key(monkeypatch):
    """環境変数 METADATA_FERNET_KEY に有効な鍵をセット。"""
    key = Fernet.generate_key().decode("ascii")
    monkeypatch.setenv("METADATA_FERNET_KEY", key)
    return key


def test_roundtrip_simple_string(fernet_key):
    """encrypt → decrypt で元の文字列が完全に復元できる。"""
    plaintext = "EAABwzLixnjYBO_super_secret_page_token_xxxx"
    ciphertext = encrypt(plaintext)
    assert isinstance(ciphertext, str)
    assert ciphertext != plaintext  # 平文がそのまま漏れていないこと
    assert decrypt(ciphertext) == plaintext


def test_roundtrip_empty_string(fernet_key):
    """空文字列も問題なくラウンドトリップできる。"""
    ciphertext = encrypt("")
    assert isinstance(ciphertext, str)
    assert ciphertext != ""  # Fernet token は空入力でも非空（ヘッダ/HMAC 含む）
    assert decrypt(ciphertext) == ""


def test_roundtrip_japanese_and_unicode(fernet_key):
    """日本語・絵文字・改行を含む文字列もラウンドトリップする。"""
    plaintext = "ご質問ありがとうございます\n田中太郎 🎉 \t末尾"
    ciphertext = encrypt(plaintext)
    assert decrypt(ciphertext) == plaintext


def test_each_encryption_produces_different_ciphertext(fernet_key):
    """Fernet は IV/timestamp を含むため、同じ平文でも毎回異なる暗号文になる。"""
    plaintext = "same-input"
    c1 = encrypt(plaintext)
    c2 = encrypt(plaintext)
    assert c1 != c2
    assert decrypt(c1) == plaintext
    assert decrypt(c2) == plaintext


def test_decrypt_with_wrong_key_raises(fernet_key, monkeypatch):
    """異なる鍵で生成された ciphertext は復号できず EncryptionError を投げる。"""
    plaintext = "secret-payload"
    ciphertext = encrypt(plaintext)

    # 別の鍵に差し替え
    other_key = Fernet.generate_key().decode("ascii")
    monkeypatch.setenv("METADATA_FERNET_KEY", other_key)
    encryption.reset_cache()

    with pytest.raises(EncryptionError):
        decrypt(ciphertext)


def test_decrypt_with_tampered_ciphertext_raises(fernet_key):
    """ciphertext を 1 文字書き換えただけでも HMAC 検証で復号失敗する。"""
    plaintext = "tamper-test"
    ciphertext = encrypt(plaintext)

    # 末尾 `=` を除いた最初の文字を別文字に差し替え
    tampered = ("X" if ciphertext[0] != "X" else "Y") + ciphertext[1:]
    with pytest.raises(EncryptionError):
        decrypt(tampered)


def test_decrypt_garbage_ciphertext_raises(fernet_key):
    """完全に無効な文字列を渡したら EncryptionError。"""
    with pytest.raises(EncryptionError):
        decrypt("this-is-not-a-fernet-token-at-all")


def test_encrypt_non_string_raises_typeerror(fernet_key):
    """plaintext が文字列でないと TypeError。"""
    for bad in [None, 123, b"bytes", ["list"], {"k": "v"}]:
        with pytest.raises(TypeError):
            encrypt(bad)  # type: ignore[arg-type]


def test_decrypt_non_string_raises_typeerror(fernet_key):
    """ciphertext が文字列でないと TypeError。"""
    for bad in [None, 123, b"bytes", ["list"]]:
        with pytest.raises(TypeError):
            decrypt(bad)  # type: ignore[arg-type]


def test_missing_key_raises_configuration_error(monkeypatch):
    """METADATA_FERNET_KEY 未設定で EncryptionConfigurationError。"""
    monkeypatch.delenv("METADATA_FERNET_KEY", raising=False)
    encryption.reset_cache()
    with pytest.raises(EncryptionConfigurationError):
        encrypt("anything")


def test_empty_key_raises_configuration_error(monkeypatch):
    """METADATA_FERNET_KEY が空文字でも EncryptionConfigurationError。"""
    monkeypatch.setenv("METADATA_FERNET_KEY", "")
    encryption.reset_cache()
    with pytest.raises(EncryptionConfigurationError):
        encrypt("anything")


def test_malformed_key_raises_configuration_error(monkeypatch):
    """METADATA_FERNET_KEY が Fernet 形式でない（短すぎ等）と EncryptionConfigurationError。"""
    monkeypatch.setenv("METADATA_FERNET_KEY", "not-a-valid-fernet-key")
    encryption.reset_cache()
    with pytest.raises(EncryptionConfigurationError):
        encrypt("anything")


def test_explicit_fernet_instance_overrides_env(monkeypatch):
    """fernet= 引数で渡した場合は環境変数を読まず、その鍵で動作する（鍵ローテーション等で使う）。"""
    monkeypatch.delenv("METADATA_FERNET_KEY", raising=False)
    encryption.reset_cache()

    custom_key = Fernet.generate_key()
    custom_fernet = Fernet(custom_key)

    plaintext = "via-explicit-fernet"
    ciphertext = encrypt(plaintext, fernet=custom_fernet)
    assert decrypt(ciphertext, fernet=custom_fernet) == plaintext


def test_lru_cache_reuses_fernet(fernet_key):
    """同じ鍵環境では _get_default_fernet が 1 度だけ評価される（パフォーマンス確認）。"""
    f1 = encryption._get_default_fernet()
    f2 = encryption._get_default_fernet()
    assert f1 is f2  # cache hit

    encryption.reset_cache()
    f3 = encryption._get_default_fernet()
    assert f3 is not f1  # cache cleared and recreated
