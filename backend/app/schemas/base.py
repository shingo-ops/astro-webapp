from __future__ import annotations

"""
共通バリデータとベースモデル。

業務APIのPydanticスキーマで共通して使うバリデーション関数やベース型を定義する。
新しいスキーマを追加する際は、ここの型を再利用して一貫性を保つ。
"""

import re

from pydantic import BaseModel, Field

# --- 共通バリデータ ---

def validate_phone(value: str | None) -> str | None:
    """電話番号バリデーション（日本の固定電話・携帯電話に対応）"""
    if value is None:
        return None
    cleaned = re.sub(r"[\s\-\(\)]", "", value)
    if not re.match(r"^(\+?\d{10,15}|0\d{9,10})$", cleaned):
        raise ValueError("電話番号の形式が正しくありません（例: 03-1234-5678, 090-1234-5678）")
    return cleaned


def validate_email_loose(value: str | None) -> str | None:
    """メールアドレスの簡易バリデーション（顧客情報用、空文字許可しない）"""
    if value is None:
        return None
    if not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", value):
        raise ValueError("メールアドレスの形式が正しくありません")
    return value.lower()


# --- ページネーション ---

class PaginationParams(BaseModel):
    """一覧取得API用のページネーションパラメータ"""
    page: int = Field(default=1, ge=1, description="ページ番号")
    per_page: int = Field(default=20, ge=1, le=100, description="1ページあたりの件数")

    @property
    def offset(self) -> int:
        return (self.page - 1) * self.per_page


class PaginatedResponse(BaseModel):
    """ページネーション付きレスポンスの共通構造"""
    total: int
    page: int
    per_page: int
    items: list
