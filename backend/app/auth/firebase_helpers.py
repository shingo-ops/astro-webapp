from __future__ import annotations

"""
Firebase Authentication helper wrappers (ADR-023).

backend から Firebase Auth ユーザを作成・削除・無効化するための薄い同期ラッパー群。
async コンテキストから使う際は ``asyncio.to_thread`` 経由で呼ぶこと
（firebase_admin.auth は同期 API）。

`set_tenant_claim` も同じ思想で `app.auth.utils` にあるが、こちらは
スタッフライフサイクル（POST/DELETE/PATCH /staff）専用の口として分離する。
"""

import logging

from firebase_admin import auth as firebase_auth


logger = logging.getLogger(__name__)


class FirebaseUserAlreadyExists(Exception):
    """Email がすでに Firebase Auth に登録されている場合に投げる。"""


class FirebaseUserNotFound(Exception):
    """対象 firebase_uid が存在しない場合に投げる。"""


def create_user(email: str, password: str, display_name: str | None = None) -> str:
    """Firebase Auth にユーザを作成し、生成された UID を返す。

    既に同一 email が存在する場合は :class:`FirebaseUserAlreadyExists` を投げる。
    """
    try:
        user = firebase_auth.create_user(
            email=email,
            password=password,
            display_name=display_name,
            email_verified=False,
            disabled=False,
        )
        return user.uid
    except firebase_auth.EmailAlreadyExistsError as e:
        raise FirebaseUserAlreadyExists(str(e)) from e


def delete_user(firebase_uid: str) -> None:
    """Firebase Auth ユーザを削除する。存在しないときは黙って通す（冪等）。"""
    try:
        firebase_auth.delete_user(firebase_uid)
    except firebase_auth.UserNotFoundError:
        logger.info("delete_user: firebase_uid=%s not found (already deleted?)", firebase_uid)


def set_disabled(firebase_uid: str, disabled: bool) -> None:
    """Firebase Auth ユーザの disabled フラグを更新する。

    `disabled=True` は実質ログイン不可（既存トークン失効までは 1 時間程度の
    タイムラグがあるが、再ログインは即時不可）。
    """
    try:
        firebase_auth.update_user(firebase_uid, disabled=disabled)
    except firebase_auth.UserNotFoundError as e:
        raise FirebaseUserNotFound(str(e)) from e
