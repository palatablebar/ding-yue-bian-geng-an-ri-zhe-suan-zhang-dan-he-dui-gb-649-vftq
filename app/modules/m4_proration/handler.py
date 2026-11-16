"""M4 路由：折算明细与重算。

重算只碰分段金额与抵扣行金额；账单由 M6 重新出，保证页面与接口看到同一份数。
"""
from __future__ import annotations

from fastapi import APIRouter, Request

from ... import web
from . import service

router = APIRouter(prefix="/api/proration", tags=["M4 按日折算"])


@router.get("")
def proration(request: Request) -> dict:
    run = web.run_or_404(request)
    store = request.app.state.store
    rows = service.segment_rows(store, run["run_id"])
    return {
        "run_id": run["run_id"],
        "summary": service.summary(store, run["run_id"]),
        "segments": rows,
    }


@router.post("")
def recompute(request: Request) -> dict:
    run = web.run_or_404(request)
    store = request.app.state.store
    settings = request.app.state.settings
    result = service.recompute_amounts(store, run["run_id"], settings)
    from ..m6_invoices import service as invoice_service

    invoices = invoice_service.rebuild(store, run["run_id"], settings)
    return {
        "run_id": run["run_id"],
        "proration": result,
        "invoices": invoices["summary"],
        "reconciliations": invoices["ledgers"],
    }
