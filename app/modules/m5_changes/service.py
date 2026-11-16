"""M5 变更与抵扣：重建分段、生成抵扣行、落库。

重算入口只做一件事：从已归一的订阅与变更重建派生结构（分段、抵扣行），
金额留给 M4，账单留给 M6；重跑结果与上次逐行一致。
"""
from __future__ import annotations

from ... import config
from ..m4_proration import prorate
from ..m6_invoices import invoice as invoice_mod
from . import credit, segments as segments_mod


def rebuild(store, run_id: str, settings) -> dict:
    subs = store.list_subscriptions(run_id)
    changes = store.list_changes(run_id)
    by_sub: dict[str, list[dict]] = {}
    for change in changes:
        by_sub.setdefault(change["sub_id"], []).append(change)

    segment_rows: list[dict] = []
    component_rows: list[dict] = []
    for sub in subs:
        invoice_id = invoice_mod.invoice_id_for(sub)
        built = segments_mod.build_segments(sub, by_sub.get(sub["sub_id"], []))
        segment_rows.extend(segments_mod.segment_rows(invoice_id, sub, built))
        period_days = int(sub["period_days"])
        for component in credit.build_components(built, period_days):
            component_rows.append({
                "invoice_id": invoice_id,
                "sub_id": sub["sub_id"],
                "seq": component.seq,
                "kind": component.kind,
                "source": component.source,
                "label": component.label,
                "days": component.days,
                "monthly": str(component.monthly),
                "exact": prorate.exact_text(component.exact),
                "cents": 0,
                "flags": component.flags,
            })

    store.put_segments(run_id, segment_rows)
    store.put_components(run_id, component_rows)
    return {
        "segments": len(segment_rows),
        "components": len(component_rows),
        "changes_applied": sum(1 for change in changes if change["applied"]),
        "changes_superseded": sum(1 for change in changes if not change["applied"]),
        "invoices": len({row["invoice_id"] for row in segment_rows}),
    }


def change_rows(store, run_id: str) -> list[dict]:
    """变更序列 + 抵扣行，页面与接口共用同一份数据。"""
    changes = store.list_changes(run_id)
    components = store.list_components(run_id)
    by_invoice: dict[str, list[dict]] = {}
    for component in components:
        by_invoice.setdefault(component["invoice_id"], []).append(component)
    subs = {sub["sub_id"]: sub for sub in store.list_subscriptions(run_id)}
    rows = []
    for change in changes:
        sub = subs.get(change["sub_id"], {})
        invoice_id = invoice_mod.invoice_id_for(sub) if sub else ""
        rows.append({
            **change,
            "account": sub.get("account", ""),
            "invoice_id": invoice_id,
            "kind_label": config.KIND_LABELS.get(change["kind"], change["kind"]),
            "components": by_invoice.get(invoice_id, []) if change["applied"] else [],
        })
    return rows


def summary(store, run_id: str) -> dict:
    changes = store.list_changes(run_id)
    components = store.list_components(run_id)
    credits = [row for row in components if row["kind"] == "credit"]
    return {
        "changes": len(changes),
        "applied": sum(1 for change in changes if change["applied"]),
        "superseded": sum(1 for change in changes if not change["applied"]),
        "flagged": sum(1 for change in changes if change["flags"]),
        "components": len(components),
        "credit_rows": len(credits),
        "credit_cents": sum(-int(row["cents"]) for row in credits),
    }
