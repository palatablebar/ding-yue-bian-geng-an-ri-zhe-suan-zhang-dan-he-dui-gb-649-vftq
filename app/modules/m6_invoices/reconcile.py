"""账单对账：四本账各自左右相等，差异逐条写清。

1. 行数账：输入数据行 = 可用订阅 + 可用变更 + 隔离行 + 丢弃重复行 + 空白行 + 重复表头
2. 期间天数账：期间天数 = 计费天数 + 免费/暂停天数
3. 金额账：分段合计（分） = 抵扣合计（分） + 账单合计（分）
4. 出账账：账单行数 = 有分段的账单数
"""
from __future__ import annotations

from decimal import Decimal

from ... import config

LEDGERS = (
    ("rows", "行数账"),
    ("days", "期间天数账"),
    ("amount", "金额账"),
    ("invoices", "出账账"),
)


def _status(diff) -> str:
    return "ok" if diff == 0 else "mismatch"


def row_ledger(counters: dict) -> dict:
    left = int(counters.get("rows_read", 0))
    right = (int(counters.get("subs_kept", 0)) + int(counters.get("changes_kept", 0))
             + int(counters.get("quarantined_rows", 0))
             + int(counters.get("dropped_dup", 0))
             + int(counters.get("blank_rows", 0))
             + int(counters.get("repeated_headers", 0)))
    return {
        "ledger": "rows", "label": "行数账",
        "left_text": str(left), "right_text": str(right),
        "diff_text": str(left - right), "status": _status(left - right),
        "note": "可用 + 隔离 + 丢弃 + 空白 + 重复表头",
    }


def day_ledger(invoices: list[dict]) -> dict:
    left = sum(int(row["period_days"]) for row in invoices)
    right = sum(int(row["billed_days"]) + int(row["free_days"]) for row in invoices)
    return {
        "ledger": "days", "label": "期间天数账",
        "left_text": str(left), "right_text": str(right),
        "diff_text": str(left - right), "status": _status(left - right),
        "note": "计费天数 + 免费/暂停天数",
    }


def amount_ledger(invoices: list[dict], components: list[dict],
                  segments: list[dict]) -> dict:
    charge = sum(int(row["cents"]) for row in components if row["kind"] == "charge")
    credit = -sum(int(row["cents"]) for row in components if row["kind"] == "credit")
    billed = sum(int(row["total_cents"]) for row in invoices)
    left = charge
    right = credit + billed
    exact_segments = sum((Decimal(row["amount_exact"]) for row in segments), Decimal("0"))
    exact_invoices = sum((Decimal(row["exact_total"]) for row in invoices), Decimal("0"))
    gap = exact_segments - exact_invoices
    return {
        "ledger": "amount", "label": "金额账",
        "left_text": str(left), "right_text": str(right),
        "diff_text": str(left - right), "status": _status(left - right),
        "note": f"单位分；精确额差 {gap}",
    }


def invoice_ledger(invoices: list[dict], segments: list[dict]) -> dict:
    left = len(invoices)
    right = len({row["invoice_id"] for row in segments})
    return {
        "ledger": "invoices", "label": "出账账",
        "left_text": str(left), "right_text": str(right),
        "diff_text": str(left - right), "status": _status(left - right),
        "note": "账单行数 = 有分段的账单数",
    }


def build(*, counters: dict, invoices: list[dict], segments: list[dict],
          components: list[dict]) -> list[dict]:
    rows = [
        row_ledger(counters),
        day_ledger(invoices),
        amount_ledger(invoices, components, segments),
        invoice_ledger(invoices, segments),
    ]
    for index, row in enumerate(rows):
        row["seq"] = index
    return rows


def overall(ledgers: list[dict]) -> dict:
    mismatches = [row["ledger"] for row in ledgers if row["status"] != "ok"]
    return {
        "ledgers": len(ledgers),
        "ok": len(ledgers) - len(mismatches),
        "mismatched": mismatches,
        "status": "ok" if not mismatches else "mismatch",
    }


def totals(counters: dict, invoices: list[dict], segments: list[dict],
           components: list[dict]) -> dict:
    charge = sum(int(row["cents"]) for row in components if row["kind"] == "charge")
    credit = -sum(int(row["cents"]) for row in components if row["kind"] == "credit")
    return {
        "subs_kept": int(counters.get("subs_kept", 0)),
        "changes_kept": int(counters.get("changes_kept", 0)),
        "quarantined_rows": int(counters.get("quarantined_rows", 0)),
        "dropped_dup": int(counters.get("dropped_dup", 0)),
        "blank_rows": int(counters.get("blank_rows", 0)),
        "rows_read": int(counters.get("rows_read", 0)),
        "invoices": len(invoices),
        "segments": len(segments),
        "components": len(components),
        "period_days": sum(int(row["period_days"]) for row in invoices),
        "billed_days": sum(int(row["billed_days"]) for row in invoices),
        "free_days": sum(int(row["free_days"]) for row in invoices),
        "charge_cents": charge,
        "credit_cents": credit,
        "invoice_cents": sum(int(row["total_cents"]) for row in invoices),
        "zero_invoices": sum(1 for row in invoices if row["total_cents"] == 0),
        "segment_exact_total": str(sum(
            (Decimal(row["amount_exact"]) for row in segments), Decimal("0"))),
        "money_unit": config.MONEY_UNIT,
    }
