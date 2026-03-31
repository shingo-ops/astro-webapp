import logging

import bcrypt
from firebase_admin import auth as firebase_auth

logger = logging.getLogger(__name__)


def set_tenant_claim(firebase_uid: str, tenant_id: int) -> None:
    """FirebaseユーザーにカスタムクレームとしてテナントIDを設定する。"""
    firebase_auth.set_custom_user_claims(firebase_uid, {"tenant_id": tenant_id})


def hash_password(password: str) -> str:
    """パスワードをbcryptでハッシュ化する。DBにはハッシュのみ保存。"""
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, hashed: str) -> bool:
    """入力パスワードとDBのハッシュを比較する。元のパスワードを知る必要はない。"""
    return bcrypt.checkpw(password.encode("utf-8"), hashed.encode("utf-8"))
