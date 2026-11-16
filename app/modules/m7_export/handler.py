"""M7 路由：账单 CSV、分段 CSV、运行清单 JSON。"""
from __future__ import annotations

from fastapi import APIRouter, Request, Response

from ... import web
from . import service

router = APIRouter(prefix="/api/export", tags=["M7 导出"])


@router.get("/invoices.csv")
def invoices_csv(request: Request) -> Response:
    run = web.run_or_404(request)
    check = request.app.state.ctx.check_of(run)
    data = service.invoices_payload(request.app.state.store, run["run_id"], check)
    return Response(
        content=data["csv"], media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition":
                 f'attachment; filename="{data["filename"]}"',
                 "X-Row-Count": str(data["count"])},
    )


@router.get("/segments.csv")
def segments_csv(request: Request) -> Response:
    run = web.run_or_404(request)
    data = service.segments_payload(request.app.state.store, run["run_id"])
    return Response(
        content=data["csv"], media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition":
                 f'attachment; filename="{data["filename"]}"',
                 "X-Row-Count": str(data["count"])},
    )


@router.get("/manifest.json")
def manifest_json(request: Request) -> Response:
    run = web.run_or_404(request)
    data = service.manifest_payload(request.app.state.store, run["run_id"])
    return Response(
        content=data["json"], media_type="application/json; charset=utf-8",
        headers={"Content-Disposition":
                 f'attachment; filename="{data["filename"]}"'},
    )
