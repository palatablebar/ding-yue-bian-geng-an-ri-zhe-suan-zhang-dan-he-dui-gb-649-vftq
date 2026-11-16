"""更正文件归一与命中校验（纯逻辑，不碰库）。

规则：
- 更正文件沿用订阅表列契约，经 M1 同一套读取/解码/列数检查；
- 每行先按 M3 同一套金额/日期/时区/状态规则归一，自身仍非法的行带原因码拒绝；
- 合法行必须命中基线隔离区中一条「未结案的 error 级订阅记录」：
  主键订阅号，同一订阅号有多条时用「原行号」列（或文件/行号）消歧；
- 任一行不满足则整份拒绝（all-or-nothing），不产生半成品。
"""
from __future__ import annotations

from dataclasses import dataclass, field

from ...reasons import label_of
from ..m1_ingest import columns as column_mod
from ..m2_calendar import service as calendar_service
from ..m3_quality import rules

# 更正文件允许携带的可选定位列
ROW_NO_ALIASES = ("原行号", "原始行号", "隔离行号", "源行号")
FILE_ALIASES = ("原文件", "来源文件", "源文件")


@dataclass
class CorrectionRow:
    sub_id: str
    record: dict
    quarantine: dict
    row_no_hint: int | None = None
    file_hint: str = ""


@dataclass
class ValidationResult:
    ok: bool
    rows: list[CorrectionRow] = field(default_factory=list)
    rejected: list[dict] = field(default_factory=list)
    header_unknown: list[str] = field(default_factory=list)


def _reject(row_no: int, code: str, *, field_name: str = "", raw: str = "",
            detail: str = "") -> dict:
    return {
        "row_no": int(row_no),
        "code": code,
        "label": label_of(code),
        "field": field_name,
        "raw_value": raw,
        "detail": detail,
    }


def _extra_index(header: list[str], names: tuple[str, ...]) -> int | None:
    for index, name in enumerate(header):
        if name.strip() in names:
            return index
    return None


def _open_error_quarantine(entries: list[dict], sub_file: str,
                           row_sub_index: dict[int, str]) -> dict[str, list[dict]]:
    """基线里仍未结案的 error 级订阅隔离记录，按订阅号分组。

    订阅号不从隔离原值猜测，而由服务层从原始 CSV 按行号重新解析得到 row_sub_index；
    拿不到订阅号的行（如业务键缺失）无法定向补入，自然排除。
    """
    grouped: dict[str, list[dict]] = {}
    for entry in entries:
        if entry.get("resolved") or entry.get("level") != "error":
            continue
        if entry.get("file") != sub_file:
            continue
        sub_id = row_sub_index.get(int(entry.get("row_no", 0)), "").strip()
        if not sub_id:
            continue
        grouped.setdefault(sub_id, []).append(entry)
    return grouped


def validate(table, base_subscriptions: list[dict], base_quarantine: list[dict],
             settings, row_sub_index: dict[int, str] | None = None) -> ValidationResult:
    """返回校验结果；ok=False 时 rejected 列出每条拒绝原因，调用方整份驳回。"""
    mapping = column_mod.sub_header(table.header)
    result = ValidationResult(ok=False)
    result.header_unknown = list(mapping.unknown)
    missing = column_mod.required_missing(mapping, column_mod.SUB_REQUIRED)
    if table.state_code or not mapping.complete:
        code = table.state_code or "R_HEADER_MISSING"
        result.rejected.append(_reject(0, code, field_name=",".join(missing),
                                       raw=",".join(table.header),
                                       detail="更正文件表头不可用，整份拒绝"))
        return result

    row_no_idx = _extra_index(table.header, ROW_NO_ALIASES)
    file_idx = _extra_index(table.header, FILE_ALIASES)
    header_len = len(table.header)
    sub_file = (base_subscriptions[0]["source_file"] if base_subscriptions
                else settings.default_subscriptions)
    open_quarantine = _open_error_quarantine(
        base_quarantine, sub_file, row_sub_index or {})
    existing_ids = {sub["sub_id"] for sub in base_subscriptions}
    seen_in_file: set[str] = set()
    rows: list[CorrectionRow] = []

    for row in table.rows:
        row_no = row.row_no
        if not column_mod.column_count_ok(row.fields, header_len):
            result.rejected.append(_reject(
                row_no, "R_COLUMN_COUNT", field_name="列数",
                raw=f"{len(row.fields)}列/表头{header_len}列"))
            continue
        sub_id = mapping.value(row.fields, "sub_id").strip()
        if not sub_id:
            result.rejected.append(_reject(row_no, "R_KEY_MISSING",
                                           field_name="订阅号", raw=row.raw))
            continue
        if sub_id in seen_in_file:
            result.rejected.append(_reject(
                row_no, "R_CORRECTION_DUP_KEY", field_name="订阅号", raw=sub_id,
                detail="一份更正文件里同一订阅号只能出现一次"))
            continue
        hint = None
        if row_no_idx is not None and row_no_idx < len(row.fields):
            hint_text = row.fields[row_no_idx].strip()
            if hint_text.isdigit():
                hint = int(hint_text)
        file_hint = ""
        if file_idx is not None and file_idx < len(row.fields):
            file_hint = row.fields[file_idx].strip()

        candidates = open_quarantine.get(sub_id, [])
        if not candidates:
            if sub_id in existing_ids:
                result.rejected.append(_reject(
                    row_no, "R_CORRECTION_NO_QUARANTINE", field_name="订阅号", raw=sub_id,
                    detail="该订阅在基线中已是可用行，定向补入不允许改写已确认数据"))
            else:
                result.rejected.append(_reject(
                    row_no, "R_CORRECTION_NO_QUARANTINE", field_name="订阅号", raw=sub_id,
                    detail="隔离区没有该订阅未结案的错误记录"))
            continue
        matched = _match_quarantine(candidates, hint, file_hint)
        if matched is None:
            detail = "同一订阅号有多条隔离记录，请用「原行号」列指定" if len(candidates) > 1 \
                else "隔离记录已结案或原文件不匹配"
            result.rejected.append(_reject(
                row_no, "R_CORRECTION_ALREADY_DONE", field_name="原行号",
                raw=str(hint or ""), detail=detail))
            continue

        record, bad = _normalize_row(mapping, row.fields, table, settings)
        if bad is not None:
            result.rejected.append(_reject(row_no, bad["code"],
                                           field_name=bad["field"], raw=bad["raw"],
                                           detail=bad.get("detail", "")))
            continue

        record["sub_id"] = sub_id
        record["source_file"] = table.name
        record["row_no"] = row_no
        record["base_row_no"] = int(matched["row_no"])
        record["base_file"] = matched["file"]
        flags = list(record.get("flags", []))
        if "R_CORRECTED_ROW" not in flags:
            flags.append("R_CORRECTED_ROW")
        record["flags"] = flags
        seen_in_file.add(sub_id)
        rows.append(CorrectionRow(sub_id=sub_id, record=record, quarantine=matched,
                                  row_no_hint=hint, file_hint=file_hint))

    result.rows = rows
    result.ok = not result.rejected and bool(rows)
    if not rows and not result.rejected:
        result.rejected.append(_reject(0, "R_KEY_MISSING", detail="更正文件没有数据行"))
        result.ok = False
    return result


def _match_quarantine(candidates: list[dict], hint: int | None,
                      file_hint: str) -> dict | None:
    if file_hint:
        narrowed = [item for item in candidates if item["file"] == file_hint]
        if narrowed:
            candidates = narrowed
    if hint is not None:
        for item in candidates:
            if int(item["row_no"]) == hint:
                return item
        return None
    return candidates[0] if len(candidates) == 1 else None


def _normalize_row(mapping, fields: list[str], table, settings) -> tuple[dict, dict | None]:
    """与 M3 同规则归一单行；返回 (record, bad)。"""
    price = rules.normalize_money(mapping.value(fields, "price"))
    if price.code:
        return {}, {"code": price.code, "field": "月价",
                    "raw": mapping.value(fields, "price")}
    start = rules.normalize_date(mapping.value(fields, "period_start"))
    end = rules.normalize_date(mapping.value(fields, "period_end"))
    if start.code or end.code:
        return {}, {"code": start.code or end.code, "field": "期间",
                    "raw": f"{mapping.value(fields, 'period_start')}~"
                           f"{mapping.value(fields, 'period_end')}"}
    if start.value is None or end.value is None:
        return {}, {"code": "R_PERIOD_MISSING", "field": "期间", "raw": ""}
    if end.value < start.value:
        return {}, {"code": "R_PERIOD_REVERSED", "field": "期间止",
                    "raw": f"{start.value}~{end.value}"}
    if end.value == start.value:
        return {}, {"code": "R_PERIOD_ZERO", "field": "期间",
                    "raw": str(start.value)}
    tz_text = mapping.value(fields, "tz").strip()
    tz_parsed = rules.parse_zone(tz_text)
    if tz_parsed.code:
        return {}, {"code": tz_parsed.code, "field": "时区", "raw": tz_text}
    state = rules.normalize_state(mapping.value(fields, "state"))
    if state.code:
        return {}, {"code": state.code, "field": "状态",
                    "raw": mapping.value(fields, "state")}
    record = {
        "account": mapping.value(fields, "account").strip(),
        "plan": mapping.value(fields, "plan").strip(),
        "price_text": mapping.value(fields, "price").strip(),
        "monthly": price.value,
        "period_start": start.value.isoformat(),
        "period_end": end.value.isoformat(),
        "tz": tz_text or settings.display_tz,
        "state": state.value,
        "period_days": calendar_service.period_days(start.value.isoformat(),
                                                    end.value.isoformat()),
        "leap": int(calendar_service.leap_of(start.value.isoformat(),
                                             end.value.isoformat())),
        "flags": list(price.flags),
    }
    return record, None
