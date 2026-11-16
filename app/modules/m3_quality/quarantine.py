"""隔离区：条目构造、原因分布、可导出的证据行。

隔离区是给人复核的：每条都带文件、原始行号、字段、原值与原因码，
导出的 CSV 与页面表格用同一份数据。
"""
from __future__ import annotations

from ... import reasons

CSV_HEADER = ["文件", "行号", "级别", "原因码", "原因", "字段", "原值", "说明"]


def entry(*, file: str, row_no: int, code: str, field: str = "",
          raw_value: str = "", detail: str = "") -> dict:
    level = reasons.level_of(code)
    return {
        "file": file,
        "row_no": int(row_no),
        "code": code,
        "level": level,
        "level_label": reasons.LEVEL_LABELS.get(level, level),
        "label": reasons.label_of(code),
        "field": field,
        "raw_value": raw_value,
        "detail": detail,
    }


def count_by_code(entries: list[dict]) -> dict:
    counts: dict[str, int] = {}
    for item in entries:
        counts[item["code"]] = counts.get(item["code"], 0) + 1
    return dict(sorted(counts.items()))


def distribution(entries: list[dict]) -> list[dict]:
    """按原因码聚合：条数、级别、说明，按级别与条数排序。"""
    buckets: dict[str, dict] = {}
    for item in entries:
        level = item.get("level") or reasons.level_of(item["code"])
        bucket = buckets.setdefault(item["code"], {
            "code": item["code"],
            "level": level,
            "level_label": reasons.LEVEL_LABELS.get(level, level),
            "label": reasons.label_of(item["code"]),
            "count": 0,
        })
        bucket["count"] += 1
    order = {"error": 0, "warn": 1, "info": 2}
    return sorted(buckets.values(),
                  key=lambda row: (order.get(row["level"], 9), -row["count"], row["code"]))


def csv_rows(entries: list[dict]) -> list[list[str]]:
    rows = []
    for item in entries:
        level = item.get("level") or reasons.level_of(item["code"])
        rows.append([
            item["file"], str(item["row_no"]),
            item.get("level_label") or reasons.LEVEL_LABELS.get(level, level),
            item["code"], reasons.label_of(item["code"]), item.get("field", ""),
            item.get("raw_value", ""), item.get("detail", ""),
        ])
    return rows


def catalog() -> list[dict]:
    return reasons.catalog()
