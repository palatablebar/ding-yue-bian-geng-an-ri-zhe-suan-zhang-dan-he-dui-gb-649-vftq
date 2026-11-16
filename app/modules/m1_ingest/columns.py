"""列契约：中文表头 → 规范键、必需列检查、行取值。

列名允许别名（订阅ID/订阅号…），未知列只告警不阻断：上游改列名不应让整批失败，
但缺必需列必须给原因码，而不是让后面按空值算钱。
"""
from __future__ import annotations

from dataclasses import dataclass, field

from ... import config


@dataclass
class HeaderMap:
    canonical: dict[str, int] = field(default_factory=dict)
    missing: list[str] = field(default_factory=list)
    unknown: list[str] = field(default_factory=list)

    def value(self, row: list[str], key: str) -> str:
        index = self.canonical.get(key)
        if index is None or index >= len(row):
            return ""
        return row[index]

    @property
    def complete(self) -> bool:
        return not self.missing


def _lookup(text: str, spec: dict) -> str | None:
    clean = text.strip().replace("\ufeff", "").replace("（", "(").replace("）", ")")
    for canonical, (_label, aliases) in spec.items():
        for alias in aliases:
            if clean == alias or clean.replace(" ", "") == alias.replace(" ", ""):
                return canonical
    return None


def map_header(header: list[str], spec: dict) -> HeaderMap:
    result = HeaderMap()
    for index, name in enumerate(header):
        canonical = _lookup(name, spec)
        if canonical is None:
            result.unknown.append(name)
        elif canonical not in result.canonical:
            result.canonical[canonical] = index
    result.missing = [key for key in spec if key not in result.canonical]
    return result


def sub_header(header: list[str]) -> HeaderMap:
    return map_header(header, config.SUB_COLUMNS)


def change_header(header: list[str]) -> HeaderMap:
    return map_header(header, config.CHANGE_COLUMNS)


def required_missing(mapping: HeaderMap, required: tuple[str, ...]) -> list[str]:
    return [key for key in required if key not in mapping.canonical]


SUB_REQUIRED = ("sub_id", "price", "period_start", "period_end", "state")
CHANGE_REQUIRED = ("change_id", "sub_id", "effective", "kind")


def looks_like_header(fields: list[str], spec: dict) -> bool:
    return sum(1 for name in fields if _lookup(name, spec) is not None) >= 2


def column_count_ok(row_fields: list[str], header_len: int) -> bool:
    """严格等长；多一列、少一列都按列数不符隔离，不做补空。"""
    return len(row_fields) == header_len
