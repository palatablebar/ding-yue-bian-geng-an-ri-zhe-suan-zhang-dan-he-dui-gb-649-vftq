"""M6 路由：账单、账单明细、对账四账。"""
from __future__ import annotations

from fastapi import APIRouter, Request

from ... import web
from . import service

router = APIRouter(prefix="/api", tags=["M6 账单对账"])


@router.get("/invoices")
def invoices(request: Request) -> dict:
    run = web.run_or_404(request)
    store = request.app.state.store
    return {"run_id": run["run_id"], **service.overview(store, run["run_id"])}


@router.get("/invoices/{invoice_id}")
def invoice_detail(request: Request, invoice_id: str) -> dict:
    run = web.run_or_404(request)
    data = service.detail(request.app.state.store, run["run_id"], invoice_id)
    if data is None:
        from ...errors import NotFound

        raise NotFound(f"账单不存在：{invoice_id}", code="E_NO_INVOICE")
    return {"run_id": run["run_id"], **data}


@router.get("/reconcile")
def reconcile(request: Request) -> dict:
    run = web.run_or_404(request)
    store = request.app.state.store
    return {
        "run_id": run["run_id"],
        "ledgers": store.list_reconciliations(run["run_id"]),
        "totals": store.list_totals(run["run_id"]),
    }
