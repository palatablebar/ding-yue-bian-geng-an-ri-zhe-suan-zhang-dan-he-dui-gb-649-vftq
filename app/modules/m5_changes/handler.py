"""M5 路由：变更序列、抵扣行、重算。"""
from __future__ import annotations

from fastapi import APIRouter, Request

from ... import web
from . import service

router = APIRouter(prefix="/api/changes", tags=["M5 变更抵扣"])


@router.get("")
def changes(request: Request) -> dict:
    run = web.run_or_404(request)
    store = request.app.state.store
    return {
        "run_id": run["run_id"],
        "summary": service.summary(store, run["run_id"]),
        "changes": service.change_rows(store, run["run_id"]),
    }


@router.post("")
def rebuild(request: Request) -> dict:
    run = web.run_or_404(request)
    store = request.app.state.store
    settings = request.app.state.settings
    built = service.rebuild(store, run["run_id"], settings)
    from ..m4_proration import service as proration_service
    from ..m6_invoices import service as invoice_service

    amounts = proration_service.recompute_amounts(store, run["run_id"], settings)
    invoices = invoice_service.rebuild(store, run["run_id"], settings)
    return {
        "run_id": run["run_id"],
        "changes": built,
        "proration": amounts,
        "invoices": invoices["summary"],
        "reconciliations": invoices["ledgers"],
    }
