from __future__ import annotations

"""
スタッフライフサイクル 3 層同期サービス（ADR-023）。

Sales Anchor の認証は ① Firebase Auth、② ``public.users``、③ ``tenant_XXX.staff``
の 3 層で構成される。ログインは ``backend/app/auth/dependencies.py`` が
``public.users`` を email で引く設計のため、3 層に揃って登録されていないユーザは
401 で拒否される。

本モジュールはスタッフ追加・削除・status 変更を 3 層すべてに伝播させる責務を持つ。

orchestration の方針:
  - 副作用順序: Firebase Auth → public.users → tenant.staff
  - Firebase Auth は外部 API のためトランザクション境界の外側。途中失敗時は
    補償的に Firebase ユーザを削除して整合性を保つ。
  - DB は単一 AsyncSession 内で flush しつつ commit はルータ側で行う。
"""

import asyncio
import logging
from dataclasses import dataclass

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import firebase_helpers
from app.auth.utils import generate_password, hash_password, set_tenant_claim
from app.models import User


logger = logging.getLogger(__name__)


@dataclass
class StaffProvisionResult:
    """provision_staff の戻り値。

    provisional_password はルータ側から API レスポンスとして 1 度だけ返し、
    監査ログ・DB には保存しない（平文流出を避けるため）。
    """

    user_id: int
    firebase_uid: str
    provisional_password: str


async def provision_user_layers(
    *,
    db: AsyncSession,
    tenant_id: int,
    email: str,
    username: str,
    full_name: str | None = None,
    existing_firebase_uid: str | None = None,
) -> StaffProvisionResult:
    """Firebase Auth と ``public.users`` を整合した状態で作成する。

    ``tenant_XXX.staff`` への INSERT は呼び出し側 (router) が引き続き担う。
    本関数は public 側の 2 層のみを面倒見る。

    引数:
      existing_firebase_uid:
        管理者が「既に Firebase Auth に存在するアカウント」を staff に紐づけたい
        場合のオーバーライド。指定があれば Firebase 側は新規作成しない。
        この場合 provisional_password は空文字を返す。

    例外:
      HTTPException(409): email がすでに ``public.users`` または Firebase Auth に存在
      HTTPException(500): Firebase 連携失敗
    """
    dup = await db.execute(select(User).where(User.email == email))
    if dup.scalar_one_or_none() is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="このメールアドレスは既にユーザ登録されています",
        )

    if existing_firebase_uid:
        firebase_uid = existing_firebase_uid
        provisional_password = ""
        # 既存 firebase ユーザでも tenant claim を付け直す（テナント移管含む冪等処理）
        try:
            await asyncio.to_thread(set_tenant_claim, firebase_uid, tenant_id)
        except Exception as e:
            logger.exception("set_tenant_claim failed for existing uid=%s", firebase_uid)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Firebase 連携に失敗しました（custom claim 設定）",
            ) from e
    else:
        provisional_password = generate_password(16)
        try:
            firebase_uid = await asyncio.to_thread(
                firebase_helpers.create_user,
                email,
                provisional_password,
                full_name or username,
            )
        except firebase_helpers.FirebaseUserAlreadyExists as e:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="このメールアドレスは既に Firebase Authentication に登録されています",
            ) from e
        except Exception as e:
            logger.exception("firebase create_user failed for email=%s", email)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Firebase ユーザ作成に失敗しました",
            ) from e

        try:
            await asyncio.to_thread(set_tenant_claim, firebase_uid, tenant_id)
        except Exception:
            # tenant claim 失敗時は Firebase ユーザを巻き戻して 500 を返す
            logger.exception("set_tenant_claim failed; rolling back firebase user uid=%s", firebase_uid)
            await asyncio.to_thread(firebase_helpers.delete_user, firebase_uid)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Firebase 連携に失敗しました（custom claim 設定）",
            )

    try:
        user = User(
            tenant_id=tenant_id,
            username=username,
            email=email,
            password_hash=hash_password(provisional_password) if provisional_password else hash_password(generate_password(32)),
            full_name=full_name,
            role="user",
            is_active=True,
        )
        db.add(user)
        await db.flush()
    except IntegrityError as e:
        # public.users 側で重複（email UNIQUE 等）した場合は Firebase 側を巻き戻す
        if not existing_firebase_uid:
            await asyncio.to_thread(firebase_helpers.delete_user, firebase_uid)
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="public.users への作成に失敗しました（email 重複等）",
        ) from e
    except Exception:
        if not existing_firebase_uid:
            await asyncio.to_thread(firebase_helpers.delete_user, firebase_uid)
        raise

    return StaffProvisionResult(
        user_id=user.id,
        firebase_uid=firebase_uid,
        provisional_password=provisional_password,
    )


async def deprovision_user_layers(
    *,
    db: AsyncSession,
    user_id: int | None,
    firebase_uid: str | None,
) -> None:
    """``public.users`` と Firebase Auth から削除する（``staff`` 行の削除はルータ側）。

    user_id / firebase_uid のいずれかが None なら、そのレイヤーはスキップする
    （該当 staff が当該レイヤーと紐づいていないケース）。Firebase 側は存在しない
    uid に対しても黙って通す（冪等）。
    """
    if firebase_uid:
        try:
            await asyncio.to_thread(firebase_helpers.delete_user, firebase_uid)
        except Exception:
            logger.exception("firebase delete_user failed (continuing) uid=%s", firebase_uid)

    if user_id is not None:
        result = await db.execute(select(User).where(User.id == user_id))
        user = result.scalar_one_or_none()
        if user is not None:
            await db.delete(user)
            await db.flush()


async def sync_user_active_flag(
    *,
    db: AsyncSession,
    user_id: int | None,
    firebase_uid: str | None,
    staff_status: str,
) -> None:
    """staff.status と ``public.users.is_active`` / Firebase ``disabled`` を同期する。

    マッピング:
      - staff.status == "active"   → users.is_active = True,  firebase.disabled = False
      - staff.status == "inactive" → users.is_active = False, firebase.disabled = True
      - staff.status == "pending"  → users.is_active = False, firebase.disabled = True
        （pending = 招待中、初回ログインで MFA 設定 → admin が active 化）
    """
    is_active = staff_status == "active"

    if user_id is not None:
        result = await db.execute(select(User).where(User.id == user_id))
        user = result.scalar_one_or_none()
        if user is not None:
            user.is_active = is_active
            await db.flush()

    if firebase_uid:
        try:
            await asyncio.to_thread(firebase_helpers.set_disabled, firebase_uid, not is_active)
        except firebase_helpers.FirebaseUserNotFound:
            logger.warning("sync_user_active_flag: firebase uid=%s not found", firebase_uid)
        except Exception:
            logger.exception("firebase set_disabled failed (continuing) uid=%s", firebase_uid)
