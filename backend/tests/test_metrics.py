from __future__ import annotations

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.metrics import register_metrics


@pytest.mark.asyncio
async def test_metrics_endpoint_exports_http_metrics():
    app = FastAPI()

    @app.get("/ping")
    async def ping():
        return {"ok": True}

    register_metrics(app)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        ping_response = await client.get("/ping")
        metrics_response = await client.get("/metrics")

    assert ping_response.status_code == 200
    assert metrics_response.status_code == 200
    assert "text/plain" in metrics_response.headers["content-type"]
    assert 'http_requests_total{handler="/ping",method="GET",status="200"}' in metrics_response.text
    assert "http_request_duration_seconds_bucket" in metrics_response.text


@pytest.mark.asyncio
async def test_metrics_uses_request_path_when_route_is_missing():
    app = FastAPI()
    register_metrics(app)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/missing")
        metrics_response = await client.get("/metrics")

    assert response.status_code == 404
    assert 'http_requests_total{handler="/missing",method="GET",status="404"}' in metrics_response.text
