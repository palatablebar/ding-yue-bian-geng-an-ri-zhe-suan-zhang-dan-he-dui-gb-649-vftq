"""M1 路由：采信样例、批次列表、批次摘要。"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, Request

from ... import web
from ...errors import BadRequest
from . import service

router = APIRouter(prefix="/api", tags=["M1 订阅采信"])


@router.post("/subscriptions/import")
def import_sample(request: Request,
                  payload: dict[str, Any] | None = Body(default=None)) -> dict:
    settings = request.app.state.settings
    store = request.app.state.store
    body = payload or {}
    sub_name = body.get("subscriptions")
    change_name = body.get("changes")
    for value in (sub_name, change_name):
        if value is not None and (not isinstance(value, str) or not value.strip()):
            raise BadRequest("文件名不能为空", code="E_BAD_FILE_NAME")
    data = service.import_sample(store, settings, sub_name, change_name)
    data["check_digit"] = data.get("check_digit") or ""
    return data


@router.get("/runs")
def runs(request: Request, limit: int = 20) -> dict:
    store = request.app.state.store
    rows = service.run_rows(store, max(1, min(int(limit), 100)))
    return {"total": len(rows), "runs": rows}


@router.get("/runs/latest")
def latest(request: Request) -> dict:
    run = web.run_or_404(request)
    return service.summary(request.app.state.store, run)
