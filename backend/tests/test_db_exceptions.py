"""
app/routers/_utils.py の handle_db_exceptions デコレーターのテスト (#20)。

実行:
    pytest backend/tests/test_db_exceptions.py -v
"""

from __future__ import annotations

import os

os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")

import pytest
from fastapi import HTTPException
from sqlalchemy.exc import OperationalError, SQLAlchemyError


class TestHandleDbExceptions:
    """handle_db_exceptions デコレーターのテスト。"""

    @pytest.mark.asyncio
    async def test_operational_error_returns_503(self):
        """OperationalError → 503。"""
        from app.routers._utils import handle_db_exceptions

        @handle_db_exceptions
        async def broken_endpoint():
            raise OperationalError("Connection refused", None, None)

        with pytest.raises(HTTPException) as exc_info:
            await broken_endpoint()

        assert exc_info.value.status_code == 503
        assert "データベース" in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_sqlalchemy_error_returns_500(self):
        """SQLAlchemyError（一般）→ 500。"""
        from app.routers._utils import handle_db_exceptions

        @handle_db_exceptions
        async def broken_endpoint():
            raise SQLAlchemyError("some db error")

        with pytest.raises(HTTPException) as exc_info:
            await broken_endpoint()

        assert exc_info.value.status_code == 500

    @pytest.mark.asyncio
    async def test_http_exception_passes_through(self):
        """HTTPException は変換せずそのまま再 raise。"""
        from app.routers._utils import handle_db_exceptions

        @handle_db_exceptions
        async def endpoint_with_404():
            raise HTTPException(status_code=404, detail="Not found")

        with pytest.raises(HTTPException) as exc_info:
            await endpoint_with_404()

        assert exc_info.value.status_code == 404
        assert exc_info.value.detail == "Not found"

    @pytest.mark.asyncio
    async def test_successful_call_returns_value(self):
        """正常終了時は戻り値をそのまま返す。"""
        from app.routers._utils import handle_db_exceptions

        @handle_db_exceptions
        async def ok_endpoint():
            return {"result": "ok"}

        result = await ok_endpoint()
        assert result == {"result": "ok"}

    @pytest.mark.asyncio
    async def test_other_exception_propagates(self):
        """SQLAlchemy以外の例外はそのまま伝播する（グローバルハンドラーへ）。"""
        from app.routers._utils import handle_db_exceptions

        @handle_db_exceptions
        async def endpoint_with_runtime_error():
            raise RuntimeError("unexpected error")

        with pytest.raises(RuntimeError):
            await endpoint_with_runtime_error()
