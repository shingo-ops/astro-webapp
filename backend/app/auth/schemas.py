from __future__ import annotations

"""
後方互換性のためのリエクスポート。
実体は app.schemas.auth に移動済み。
"""

from app.schemas.auth import (  # noqa: F401
    TokenData,
    TokenResponse,
    UserLogin,
    UserRegister,
    UserResponse,
)
