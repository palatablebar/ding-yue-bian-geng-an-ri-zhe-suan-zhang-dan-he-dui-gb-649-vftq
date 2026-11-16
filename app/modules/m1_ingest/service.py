"""M1 订阅采信 + 主流程编排：读样例 → 归一/隔离 → 分段 → 折算 → 出账 → 清单。

编排留在 M1 是因为「采信一次」就是使用者眼里的一个动作；每个阶段仍然可以单独调
（M2 日历、M3 隔离区、M4 折算重算、M5 变更重算、M6 账单、M7 导出）。
"""
from __future__ import annotations

import datetime as dt
import time

from ... import config, manifest
from ..m3_quality import service as quality_service
from ..m4_proration import service as proration_service
from ..m5_changes import service as change_service
from ..m6_invoices import service as invoice_service
from . import columns as column_mod
from . import reader


def _now() -> str:
    return dt.datetime.now(config.UTC).isoformat(timespec="seconds")


def _inputs(sub_table, change_table) -> list[dict]:
    return [
        {"name": sub_table.name, "encoding": sub_table.encoding, "bytes": sub_table.size,
         "sha256": sub_table.sha256, "rows": sub_table.data_rows, "header": sub_table.header},
        {"name": change_table.name, "encoding": change_table.encoding,
         "bytes": change_table.size, "sha256": change_table.sha256,
         "rows": change_table.data_rows, "header": change_table.header},
    ]


def _stages(counters: dict, totals: dict, build: dict, prepared: dict) -> list[dict]:
    distribution = prepared["distribution"]
    top = ", ".join(f"{row['code']}×{row['count']}" for row in distribution[:3]) or "无"
    days = totals.get("period_days", 0)
    return [
        {"stage": "ingest", "in_count": counters["rows_read"],
         "out_count": counters["subs_kept"] + counters["changes_kept"],
         "quarantine_count": counters["quarantined_rows"],
         "note": "两份样例文件按编码回退链读取"},
        {"stage": "calendar", "in_count": counters["subs_kept"],
         "out_count": counters["subs_kept"], "quarantine_count": 0,
         "note": f"期间合计 {days} 天"},
        {"stage": "quality", "in_count": counters["rows_read"],
         "out_count": counters["subs_kept"] + counters["changes_kept"],
         "quarantine_count": counters["quarantined_rows"], "note": top},
        {"stage": "changes", "in_count": counters["changes_kept"],
         "out_count": counters["changes_kept"] - counters.get("changes_superseded", 0),
         "quarantine_count": 0, "note": f"分段 {build['segments']}"},
        {"stage": "proration", "in_count": build["segments"],
         "out_count": build["components"], "quarantine_count": 0,
         "note": f"精确合计 {totals.get('segment_exact_total', '0')}"},
        {"stage": "invoices", "in_count": counters["subs_kept"],
         "out_count": totals.get("invoices", 0), "quarantine_count": 0,
         "note": f"账单合计 {totals.get('invoice_cents', 0)} 分"},
    ]


def summary(store, run: dict) -> dict:
    run_id = run["run_id"]
    data = store.get_manifest(run_id) or {}
    return {
        "run_id": run_id,
        "check_digit": data.get("check_digit") or manifest.check_digit(run_id),
        "batch_key": run["batch_key"],
        "status": run["status"],
        "created_at": run["created_at"],
        "finished_at": run.get("finished_at"),
        "input_digest": run.get("input_digest", ""),
        "reused": False,
        "counters": run.get("counters", {}),
        "totals": store.list_totals(run_id),
        "ledgers": store.list_reconciliations(run_id),
        "stages": store.list_stages(run_id),
        "inputs": store.list_inputs(run_id),
        "manifest": data,
    }


def import_sample(store, settings, subscriptions: str | None = None,
                  changes: str | None = None) -> dict:
    sub_name = subscriptions or settings.default_subscriptions
    change_name = changes or settings.default_changes
    sub_table = reader.load(settings.sample_dir, sub_name)
    change_table = reader.load(settings.sample_dir, change_name)
    key = manifest.batch_key(settings.rule_version, [
        sub_table.name, sub_table.sha256, change_table.name, change_table.sha256,
    ])
    existing = store.find_run_by_key(key)
    if existing is not None:
        data = summary(store, existing)
        data["reused"] = True
        return data

    started_at = _now()
    clock = time.perf_counter()
    run_id = manifest.new_run_id()
    store.create_run({
        "run_id": run_id,
        "batch_key": key,
        "status": "running",
        "source": f"{sub_table.name} + {change_table.name}",
        "rule_version": settings.rule_version,
        "created_at": started_at,
        "params": {"subscriptions": sub_table.name, "changes": change_table.name,
                   "display_tz": settings.display_tz},
    })
    store.put_inputs(run_id, _inputs(sub_table, change_table))

    prepared = quality_service.prepare(store, run_id, sub_table, change_table, settings)
    counters = dict(prepared["counters"])
    store.update_run(run_id, counters_json=counters)

    built = change_service.rebuild(store, run_id, settings)
    amounts = proration_service.recompute_amounts(store, run_id, settings)
    invoices = invoice_service.rebuild(store, run_id, settings)
    totals = dict(invoices["totals"])
    totals["segment_exact_total"] = amounts["segment_exact_total"]

    stages = _stages(counters, totals, built, prepared)
    store.put_stages(run_id, stages)

    digest = manifest.digest_parts([item["sha256"] for item in _inputs(
        sub_table, change_table)])
    finished_at = _now()
    elapsed_ms = int((time.perf_counter() - clock) * 1000)
    store.update_run(run_id, status="done", finished_at=finished_at, input_digest=digest)
    data = manifest.build(
        run_id=run_id, batch_key=key, settings=settings,
        inputs=_inputs(sub_table, change_table),
        params={"display_tz": settings.display_tz,
                "subscriptions": sub_table.name, "changes": change_name},
        started_at=started_at, finished_at=finished_at, elapsed_ms=elapsed_ms,
        stages=stages, counters=counters, totals=totals,
        reconciliations=invoices["ledgers"],
    )
    store.put_manifest(run_id, data)

    run = store.get_run(run_id) or {"run_id": run_id, "batch_key": key,
                                    "status": "done", "created_at": started_at,
                                    "counters": counters, "input_digest": digest}
    return summary(store, run)


def run_rows(store, limit: int = 20) -> list[dict]:
    rows = []
    for run in store.list_runs(limit):
        totals = store.list_totals(run["run_id"])
        rows.append({
            "run_id": run["run_id"],
            "check_digit": manifest.check_digit(run["run_id"]),
            "status": run["status"],
            "created_at": run["created_at"],
            "source": run["source"],
            "input_digest": run["input_digest"],
            "invoices": totals.get("invoices", "0"),
            "invoice_cents": totals.get("invoice_cents", "0"),
            "quarantined_rows": run["counters"].get("quarantined_rows", 0),
        })
    return rows


def header_maps(sub_table, change_table) -> dict:
    """页面诊断用：表头到规范键的映射结果。"""
    return {
        "subscriptions": column_mod.sub_header(sub_table.header),
        "changes": column_mod.change_header(change_table.header),
    }
