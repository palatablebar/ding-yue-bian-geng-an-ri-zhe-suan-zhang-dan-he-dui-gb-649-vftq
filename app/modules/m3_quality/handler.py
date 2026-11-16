"""M3 路由：隔离区列表、原因分布、证据 CSV、原因码目录。"""
from __future__ import annotations

import csv
import io

from fastapi import APIRouter, Request, Response

from ... import web
from . import quarantine, service

router = APIRouter(prefix="/api", tags=["M3 质量隔离"])


@router.get("/quarantine")
def list_quarantine(request: Request, limit: int | None = None) -> dict:
    run = web.run_or_404(request)
    data = service.load_quarantine(request.app.state.store, run["run_id"])
    entries = data["entries"] if not limit else data["entries"][:limit]
    return {
        "run_id": run["run_id"],
        "entries": entries,
        "distribution": data["distribution"],
        "totals": data["totals"],
    }


@router.get("/quarantine.csv")
def quarantine_csv(request: Request) -> Response:
    run = web.run_or_404(request)
    entries = request.app.state.store.list_quarantine(run["run_id"])
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(quarantine.CSV_HEADER)
    writer.writerows(quarantine.csv_rows(entries))
    body = "\ufeff" + buffer.getvalue()
    return Response(
        content=body,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition":
                 f'attachment; filename="quarantine-{run["run_id"]}.csv"'},
    )


@router.get("/reasons")
def reasons_catalog() -> dict:
    catalog = service.reason_catalog()
    return {"total": len(catalog), "reasons": catalog}
