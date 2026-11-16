"""M2 路由：期间日历查询。"""
from __future__ import annotations

from fastapi import APIRouter, Query, Request

from ...errors import NotFound
from . import service

router = APIRouter(prefix="/api/calendar", tags=["M2 期间日历"])


def _require_run(request: Request) -> dict:
    run = request.app.state.ctx.require_run(request.query_params.get("run_id"))
    if run is None:
        raise NotFound("还没有批次，先在首页采信一次", code="E_NO_RUN")
    return run


@router.get("")
def calendar(request: Request) -> dict:
    run = _require_run(request)
    rows = service.period_rows(request.app.state.store, run["run_id"])
    return {
        "run_id": run["run_id"],
        "timezone": request.app.state.settings.display_tz,
        "half_open": True,
        "periods": rows,
        "totals": service.period_totals(rows),
    }


@router.get("/days")
def days(start: str = Query(...), end: str = Query(...)) -> dict:
    return service.days_query(start, end)


@router.get("/month")
def month(year: int = Query(...), month: int = Query(...)) -> dict:
    return service.month_query(year, month)
