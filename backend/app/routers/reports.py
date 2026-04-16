"""
レポートエクスポートAPI。

CSVエクスポートをCeleryタスクとして非同期実行し、
タスクIDで進捗確認・結果ダウンロードを行う。

変更履歴:
  2026-04-16: Phase 1拡張（リードCSVエクスポートを追加、require_permission統合）
"""

from __future__ import annotations

from enum import Enum

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import Response
from pydantic import BaseModel

from app.auth.dependencies import get_current_user, get_current_tenant, require_permission
from app.cache import get_redis
from app.models import User

router = APIRouter()


class ReportType(str, Enum):
    customers = "customers"
    leads = "leads"
    deals = "deals"
    orders = "orders"


class ExportRequest(BaseModel):
    report_type: ReportType


class ExportResponse(BaseModel):
    task_id: str
    message: str


class ExportStatusResponse(BaseModel):
    task_id: str
    status: str
    result: dict | None = None


@router.post(
    "/reports/export",
    response_model=ExportResponse,
    status_code=202,
    dependencies=[Depends(require_permission("reports.export"))],
)
async def request_export(
    data: ExportRequest,
    tenant_id: int = Depends(get_current_tenant),
    current_user: User = Depends(get_current_user),
):
    """CSVエクスポートをリクエストする（非同期実行）"""
    from app.tasks.reports import export_csv

    task = export_csv.delay(tenant_id, data.report_type.value)
    return ExportResponse(
        task_id=task.id,
        message=f"{data.report_type.value}のエクスポートを開始しました",
    )


@router.get(
    "/reports/{task_id}/status",
    response_model=ExportStatusResponse,
    dependencies=[Depends(require_permission("reports.view", "reports.export"))],
)
async def get_export_status(
    task_id: str,
    tenant_id: int = Depends(get_current_tenant),
    current_user: User = Depends(get_current_user),
):
    """エクスポートタスクの状態を確認する"""
    from app.celery_app import celery_app

    result = celery_app.AsyncResult(task_id)
    response = {
        "task_id": task_id,
        "status": result.status,
        "result": None,
    }

    if result.ready():
        response["result"] = result.result

    return ExportStatusResponse(**response)


@router.get(
    "/reports/{task_id}/download",
    dependencies=[Depends(require_permission("reports.view", "reports.export"))],
)
async def download_export(
    task_id: str,
    tenant_id: int = Depends(get_current_tenant),
    current_user: User = Depends(get_current_user),
):
    """エクスポート結果をCSVファイルとしてダウンロードする"""
    r = get_redis()
    if not r:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="キャッシュサービスが利用できません",
        )

    # テナントIDをキーに含めることで他テナントのデータアクセスを防止
    cache_key = f"export:{tenant_id}:{task_id}"
    csv_content = await r.get(cache_key)

    if not csv_content:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="エクスポート結果が見つかりません（期限切れの可能性があります）",
        )

    return Response(
        content=csv_content,
        media_type="text/csv",
        headers={
            "Content-Disposition": f"attachment; filename=export_{task_id}.csv",
        },
    )
