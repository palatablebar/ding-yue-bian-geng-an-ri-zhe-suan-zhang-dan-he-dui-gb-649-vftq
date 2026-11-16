"""导出 CSV：账单与分段明细，带原值、行号与标记，可直接复核。

数字一律两位小数文本（金额）或整数（天数/分），不做本地化格式，
避免 Excel 把「1,200.00」当字符串又当数字。
"""
from __future__ import annotations

import csv
import io
from decimal import Decimal

from ... import config

INVOICE_HEADER = [
    "账单号", "订阅号", "账户", "期间起", "期间止", "期间天数", "计费天数", "免费天数",
    "分段合计(元)", "抵扣合计(元)", "账单额(元)", "状态", "校验位", "标记",
]
SEGMENT_HEADER = [
    "账单号", "订阅号", "段序", "起", "止", "天数", "套餐", "状态", "月价(元)",
    "日价(元)", "分段金额(元)", "原始行号", "标记",
]


def _writer() -> tuple[io.StringIO, "csv._writer"]:
    buffer = io.StringIO()
    return buffer, csv.writer(buffer, lineterminator="\n")


def money(cents) -> str:
    return f"{Decimal(int(cents)) / 100:.2f}"


def money_text(text) -> str:
    return f"{Decimal(str(text or '0')):.2f}"


def flags_text(codes) -> str:
    return "|".join(codes or [])


def invoices_csv(rows: list[dict], check_digit: str) -> str:
    buffer, writer = _writer()
    writer.writerow(INVOICE_HEADER)
    for row in rows:
        writer.writerow([
            row["invoice_id"], row["sub_id"], row["account"], row["period_start"],
            row["period_end"], row["period_days"], row["billed_days"], row["free_days"],
            money(row["charge_cents"]), money(row["credit_cents"]),
            money(row["total_cents"]), config.INVOICE_STATUS_LABELS.get(row["status"],
                                                                        row["status"]),
            check_digit, flags_text(row["flags"]),
        ])
    return buffer.getvalue()


def segments_csv(rows: list[dict], invoice_by_id: dict) -> str:
    buffer, writer = _writer()
    writer.writerow(SEGMENT_HEADER)
    for row in rows:
        invoice = invoice_by_id.get(row["invoice_id"], {})
        writer.writerow([
            row["invoice_id"], row["sub_id"], row["seq"], row["start_date"],
            row["end_date"], row["days"], row["plan"],
            config.STATE_LABELS.get(row["state"], row["state"]),
            money_text(row["monthly"]), row.get("daily", ""),
            money(row["amount_cents"]), invoice.get("source_row", ""),
            flags_text(row["flags"]),
        ])
    return buffer.getvalue()


def with_bom(text: str) -> str:
    return "\ufeff" + text
