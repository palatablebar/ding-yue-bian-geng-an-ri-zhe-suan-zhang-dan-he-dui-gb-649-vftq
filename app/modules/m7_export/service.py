"""M7 导出：账单 CSV、分段 CSV、运行清单 JSON。

导出与页面读同一批表，导出行数与合计必须和账单页一致（对账第四本账）。
"""
from __future__ import annotations

from ..m4_proration import service as proration_service
from ..m6_invoices import service as invoice_service
from . import csv_out, manifest_out


def invoices_payload(store, run_id: str, check_digit: str) -> dict:
    rows = invoice_service.invoice_rows(store, run_id)
    text = csv_out.invoices_csv(rows, check_digit)
    return {"rows": rows, "csv": csv_out.with_bom(text),
            "filename": f"invoices-{run_id}.csv", "count": len(rows)}


def segments_payload(store, run_id: str) -> dict:
    rows = proration_service.segment_rows(store, run_id)
    invoices = {row["invoice_id"]: row for row in store.list_invoices(run_id)}
    rows.sort(key=lambda item: (item["invoice_id"], item["seq"]))
    text = csv_out.segments_csv(rows, invoices)
    return {"rows": rows, "csv": csv_out.with_bom(text),
            "filename": f"segments-{run_id}.csv", "count": len(rows)}


def manifest_payload(store, run_id: str) -> dict:
    data = store.get_manifest(run_id) or {}
    return {
        "run_id": run_id,
        "manifest": data,
        "json": manifest_out.manifest_json(data),
        "filename": manifest_out.filename(run_id),
        "verify": manifest_out.verify(data),
    }
