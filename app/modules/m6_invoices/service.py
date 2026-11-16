"""M6 账单对账：出账、四账核对、合计。

出账只读派生表（分段、抵扣行），因此重建一次不会改变输入；
同一批次重跑，账单行数与合计逐字不变。
"""
from __future__ import annotations

from ... import config
from . import invoice as invoice_mod
from . import reconcile


def _group(rows: list[dict]) -> dict[str, list[dict]]:
    grouped: dict[str, list[dict]] = {}
    for row in rows:
        grouped.setdefault(row["invoice_id"], []).append(row)
    for group in grouped.values():
        group.sort(key=lambda item: item["seq"])
    return grouped


def rebuild(store, run_id: str, settings) -> dict:
    run = store.get_run(run_id) or {}
    counters = run.get("counters", {})
    subs = {sub["sub_id"]: sub for sub in store.list_subscriptions(run_id)}
    segments = store.list_segments(run_id)
    components = store.list_components(run_id)
    segment_groups = _group(segments)
    component_groups = _group(components)

    invoices: list[dict] = []
    for invoice_id, rows in sorted(segment_groups.items()):
        sub = subs.get(rows[0]["sub_id"])
        if sub is None:
            continue
        invoices.append(invoice_mod.build_invoice(
            sub, rows, component_groups.get(invoice_id, [])))

    store.put_invoices(run_id, invoices)
    ledgers = reconcile.build(counters=counters, invoices=invoices,
                              segments=segments, components=components)
    store.put_reconciliations(run_id, ledgers)
    totals = reconcile.totals(counters, invoices, segments, components)
    store.put_totals(run_id, totals)
    return {
        "summary": {
            "invoices": len(invoices),
            "period_days": totals["period_days"],
            "charge_cents": totals["charge_cents"],
            "credit_cents": totals["credit_cents"],
            "invoice_cents": totals["invoice_cents"],
            "zero_invoices": totals["zero_invoices"],
            "money_unit": config.MONEY_UNIT,
        },
        "ledgers": ledgers,
        "totals": totals,
    }


def invoice_rows(store, run_id: str) -> list[dict]:
    from ..m4_proration import rounding

    subs = {sub["sub_id"]: sub for sub in store.list_subscriptions(run_id)}
    rows = []
    for row in store.list_invoices(run_id):
        sub = subs.get(row["sub_id"], {})
        rows.append({
            **row,
            "amount": rounding.cents_text(row["total_cents"]),
            "charge": rounding.cents_text(row["charge_cents"]),
            "credit": rounding.cents_text(row["credit_cents"]),
            "leap": bool(sub.get("leap", 0)),
            "range_label": f"[{row['period_start']}, {row['period_end']})",
        })
    return rows


def detail(store, run_id: str, invoice_id: str) -> dict | None:
    row = store.get_invoice(run_id, invoice_id)
    if row is None:
        return None
    segments = store.list_segments(run_id, invoice_id)
    components = store.list_components(run_id, invoice_id)
    return invoice_mod.detail(row, segments, components)


def overview(store, run_id: str) -> dict:
    return {
        "invoices": invoice_rows(store, run_id),
        "ledgers": store.list_reconciliations(run_id),
        "totals": store.list_totals(run_id),
    }
