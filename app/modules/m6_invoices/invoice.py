"""账单：一张订阅一个计费期间一张账单，金额以「分」整数记账。

账单金额只有一个来源：抵扣行（预缴/抵扣/补收）分配后的分。
分段金额的分只用于明细核对，两者都必须加总到同一个总额。
"""
from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP

from ... import config
from ..m4_proration import rounding


def invoice_id_for(sub: dict) -> str:
    if not sub:
        return ""
    start = str(sub.get("period_start") or "")[:7].replace("-", "")
    return f"INV-{start}-{sub.get('sub_id', '')}"


def _sum_cents(components: list[dict], kind: str) -> int:
    return sum(int(row["cents"]) for row in components if row["kind"] == kind)


def round_adjusted(components: list[dict]) -> bool:
    """分量各自四舍五入与合计四舍五入不一致时，说明用了最大余额法补差。"""
    naive = sum(int((Decimal(row["exact_text"]) * 100).quantize(
        Decimal("1"), rounding=ROUND_HALF_UP)) for row in components)
    allocated = sum(int(row["cents"]) for row in components)
    return naive != allocated


def build_invoice(sub: dict, segments: list[dict], components: list[dict]) -> dict:
    charge_cents = _sum_cents(components, "charge")
    credit_cents = -_sum_cents(components, "credit")
    total_cents = charge_cents - credit_cents
    exact_total = sum((Decimal(row["amount_exact"]) for row in segments), Decimal("0"))
    billed_days = sum(int(row["days"]) for row in segments
                      if row["state"] not in config.ZERO_RATE_STATES)
    period_days = int(sub["period_days"])
    free_days = period_days - billed_days
    flags: list[str] = []
    for row in segments:
        for code in row["flags"]:
            if code not in flags:
                flags.append(code)
    for code in sub["flags"]:
        if code not in flags:
            flags.append(code)
    if total_cents == 0:
        flags.append("R_INVOICE_ZERO")
    if components and round_adjusted(components):
        flags.append("R_ROUND_ADJUST")
    status = "zero" if total_cents == 0 else "ok"
    return {
        "invoice_id": invoice_id_for(sub),
        "sub_id": sub["sub_id"],
        "account": sub["account"],
        "period_start": sub["period_start"],
        "period_end": sub["period_end"],
        "period_days": period_days,
        "billed_days": billed_days,
        "free_days": free_days,
        "charge_cents": charge_cents,
        "credit_cents": credit_cents,
        "total_cents": total_cents,
        "exact_total": str(exact_total),
        "status": status,
        "flags": flags,
        "source_row": int(sub["row_no"]),
    }


def detail(invoice: dict, segments: list[dict], components: list[dict]) -> dict:
    return {
        "invoice": {**invoice, "amount": rounding.cents_text(invoice["total_cents"])},
        "segments": [{
            **row,
            "amount": rounding.cents_text(row["amount_cents"]),
            "state_label": config.STATE_LABELS.get(row["state"], row["state"]),
        } for row in segments],
        "components": [{**row, "amount": rounding.cents_text(row["cents"])}
                       for row in components],
    }
