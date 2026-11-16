"""M8 更正补入编排：校验 → 幂等检查 → 构建临时版本 → 单事务提交 → 四账校验 → 失败回滚。

不变量：
- 基线 run 的任何行都不被改写；更正产物是一个新 run（kind='correction'）；
- 同一更正文件（sha256）对同一条版本链重跑，复用已发布版本，绝不重复补入；
- 构建期临时 run 处于 running（latest_run 只取 done，不会顶替当前版本）；
  提交在单事务内把 run 转 done 并写发布审计，任一环节抛错则清理临时 run、
  只留一条 failed 留痕，库里当前版本仍是上一份完整旧版；
- 未受影响订阅的分段与账单逐字不变，只新增隔离行对应的账单。
"""
from __future__ import annotations

import datetime as dt
import hashlib
import time
from decimal import Decimal

from ... import config, manifest
from ...errors import Unprocessable
from ..m1_ingest import columns as column_mod
from ..m1_ingest import reader
from ..m4_proration import service as proration_service
from ..m5_changes import service as change_service
from ..m6_invoices import reconcile
from ..m6_invoices import service as invoice_service
from . import validator


def _now() -> str:
    return dt.datetime.now(config.UTC).isoformat(timespec="seconds")


def _row_sub_index(base_run: dict, settings) -> dict[int, str]:
    """从基线原始订阅 CSV 按行号重新解析订阅号，供隔离记录定向匹配。

    文件缺失（如测试构造的库）时降级为空映射，不阻断主流程。
    """
    name = base_run.get("params", {}).get("subscriptions") or settings.default_subscriptions
    try:
        table = reader.load(settings.sample_dir, name)
    except Exception:  # noqa: BLE001 - 降级：无法重读原文件时不靠行号外猜
        return {}
    mapping = column_mod.sub_header(table.header)
    index: dict[int, str] = {}
    if "sub_id" not in mapping.canonical:
        return index
    pos = mapping.canonical["sub_id"]
    for row in table.rows:
        if pos < len(row.fields):
            sub_id = row.fields[pos].strip()
            if sub_id:
                index[row.row_no] = sub_id
    return index


def _load_correction_table(store, settings, file_name: str, content: bytes | None):
    if content is not None:
        return reader.parse_table(file_name or "correction.csv", content)
    if not file_name:
        raise Unprocessable("更正文件名不能为空", code="E_CORRECTION_EMPTY")
    return reader.load(settings.sample_dir, file_name)


def _assert_ledgers_balanced(ledgers: list[dict]) -> None:
    bad = [row["ledger"] for row in ledgers if row["status"] != "ok"]
    if bad:
        raise Unprocessable(
            f"更正后对账不平（{','.join(bad)}），已回滚，基线结果保持不变",
            code="E_CORRECTION_LEDGER", detail={"ledgers": bad})


def _correction_stages(base_stages: list[dict], corrected: int,
                       totals: dict, note: str) -> list[dict]:
    stages = [dict(item) for item in base_stages]
    stages.append({
        "stage": "corrections",
        "in_count": corrected,
        "out_count": corrected,
        "quarantine_count": 0,
        "note": note,
    })
    # 质量/账单阶段的隔离计数随补入变化，写清事实让行数账可解释
    for stage in stages:
        if stage["stage"] == "quality":
            stage["note"] = f"{stage['note']}；更正补入 {corrected} 行"
        if stage["stage"] == "invoices":
            stage["note"] = f"账单合计 {totals.get('invoice_cents', 0)} 分（含更正）"
    return stages


def _jsonable(record: dict) -> dict:
    """审计条目落 JSON 前把 Decimal 等非标量转成字符串。"""
    out = {}
    for key, value in record.items():
        if isinstance(value, Decimal):
            out[key] = str(value)
        else:
            out[key] = value
    return out


def _entry_bases(store, base_run_id: str, rows: list[validator.CorrectionRow]) -> dict:
    """补入前的旧版事实：受影响订阅原隔离信息 + 旧账单额（没有账单记 0）。"""
    invoices = {row["sub_id"]: row for row in store.list_invoices(base_run_id)}
    bases: dict[str, dict] = {}
    for item in rows:
        old = invoices.get(item.sub_id)
        bases[item.sub_id] = {
            "quarantine": item.quarantine,
            "base_cents": int(old["total_cents"]) if old else 0,
            "had_invoice": old is not None,
        }
    return bases


def publish_correction(store, settings, *, base_run_id: str | None = None,
                       file_name: str = "", content: bytes | None = None,
                       mode: str = config.CORRECTION_MODE_PATCH) -> dict:
    if mode == config.CORRECTION_MODE_REPLACE:
        raise Unprocessable(
            "整批替换会重算并改变已确认账单，系统只支持定向补入（mode=patch）；"
            "如需全量重算，请以新输入走普通采信生成独立批次",
            code="E_CORRECTION_MODE")
    if mode != config.CORRECTION_MODE_PATCH:
        raise Unprocessable(f"未知更正模式：{mode}", code="E_CORRECTION_MODE")

    base = store.get_run(base_run_id) if base_run_id else store.latest_run()
    if base is None:
        raise Unprocessable("还没有可更正的基线批次", code="E_NO_RUN")
    if base.get("status") != "done":
        raise Unprocessable("基线批次未完成，不能发布更正", code="E_CORRECTION_BASE_STATE")
    # 更正基于当前所选（或最新）已完成版本依次叠加：v1 → v2 → v3，版本链不断链。
    # 幂等仍按「该版本的根基线 + 文件 sha256」判定，保证同一更正重跑不重复补入。
    base_run_id = base["run_id"]
    root = base
    guard = 0
    while root.get("base_run_id") and guard < 100:
        parent = store.get_run(root["base_run_id"])
        if parent is None:
            break
        root = parent
        guard += 1
    root_run_id = root["run_id"]

    table = _load_correction_table(store, settings, file_name, content)
    digest = hashlib.sha256(
        table.name.encode("utf-8") + b"\x00" + table.sha256.encode("utf-8")).hexdigest()

    # 幂等：同一更正文件对同一条版本链（根基线）只生效一次，重跑复用已发布版本；
    # 若上次是 failed 留痕，先清掉以便用修正后的同名文件重试。
    existing = store.find_correction_release(root_run_id, digest)
    if existing is not None:
        if existing["status"] == "published":
            return summary(store, existing["run_id"], reused=True,
                           release_id=existing["release_id"])
        store.delete_correction_release(existing["release_id"])

    base_subs = store.list_subscriptions(base_run_id)
    base_quarantine = store.list_quarantine(base_run_id)
    result = validator.validate(table, base_subs, base_quarantine, settings,
                                _row_sub_index(base, settings))
    if not result.ok:
        raise Unprocessable(
            "更正文件存在无法补入的行，整份拒绝，基线结果不变",
            code="E_CORRECTION_INVALID", detail={"rejected": result.rejected})

    started_at = _now()
    clock = time.perf_counter()
    version_no = max((int(run.get("version_no", 1))
                      for run in store.list_lineage(base_run_id)), default=1) + 1
    new_run_id = manifest.new_run_id(prefix="SC")
    release_id = f"CR-{manifest.new_run_id(prefix='R')}"
    key = manifest.batch_key(settings.rule_version, [base_run_id, digest, str(version_no)])
    affected = [item.sub_id for item in result.rows]
    bases = _entry_bases(store, base_run_id, result.rows)

    try:
        payload = _build_correction_run(
            store=store, settings=settings, base=base, base_run_id=base_run_id,
            root_run_id=root_run_id,
            new_run_id=new_run_id, release_id=release_id, key=key, table=table,
            digest=digest, result=result, bases=bases, version_no=version_no,
            started_at=started_at, clock=clock, mode=mode)
    except Exception:
        # 构建失败：删除临时 run（running，不可能成为当前版本），另写失败留痕，旧版完整
        _discard_run(store, new_run_id)
        store.create_correction_release({
            "release_id": release_id, "run_id": new_run_id, "base_run_id": base_run_id,
            "root_run_id": root_run_id,
            "batch_key": key, "status": "failed", "mode": mode, "file_name": table.name,
            "file_sha256": digest, "created_at": _now(), "affected_subs": affected,
            "rejected": result.rejected, "note": "构建失败已回滚，基线保持不变"})
        raise

    # 提交：一个事务把 run 转 done 并写 published 审计；失败则删临时 run 并留痕
    try:
        with store.transaction() as conn:
            conn.execute("UPDATE runs SET status='done', finished_at=?, input_digest=? "
                         "WHERE run_id=?",
                         (payload["finished_at"], payload["input_digest"], new_run_id))
            store.put_manifest(new_run_id, payload["manifest"], conn=conn)
            store.create_correction_release(payload["release_record"], conn=conn)
    except Exception:
        _discard_run(store, new_run_id)
        store.create_correction_release({
            "release_id": release_id, "run_id": new_run_id, "base_run_id": base_run_id,
            "root_run_id": root_run_id,
            "batch_key": key, "status": "failed", "mode": mode, "file_name": table.name,
            "file_sha256": digest, "created_at": _now(), "affected_subs": affected,
            "rejected": result.rejected, "note": "提交失败已回滚，基线保持不变"})
        raise

    return summary(store, new_run_id, reused=False, release_id=release_id)


def _discard_run(store, run_id: str) -> None:
    """删除未完成（running）的临时更正 run 及其全部行；只用于失败清理。"""
    for table in ("inputs", "subscriptions", "changes", "quarantine", "segments",
                  "components", "invoices", "stages", "totals", "reconciliations",
                  "manifests"):
        with store.connect() as conn:
            conn.execute(f"DELETE FROM {table} WHERE run_id=?", (run_id,))
    with store.connect() as conn:
        conn.execute("DELETE FROM runs WHERE run_id=? AND status!='done'", (run_id,))


def _build_correction_run(*, store, settings, base, base_run_id, root_run_id,
                          new_run_id, release_id,
                          key, table, digest, result, bases, version_no, started_at,
                          clock, mode) -> dict:
    """构建更正版本的全部数据（临时 run 处于 running），返回提交所需载荷。"""
    corrected_records = {item.sub_id: item.record for item in result.rows}
    base_inputs = store.list_inputs(base_run_id)
    base_changes = store.list_changes(base_run_id)
    base_quarantine = [dict(item) for item in store.list_quarantine(base_run_id)]
    base_stages = store.list_stages(base_run_id)

    # 1) 临时 run（running，latest_run 只取 done，绝不会顶替当前版本）
    store.create_run({
        "run_id": new_run_id, "batch_key": key, "status": "running",
        "source": f"{base['source']} + 更正 {table.name}",
        "rule_version": settings.rule_version, "created_at": started_at,
        "params": {**base.get("params", {}), "correction_file": table.name,
                   "base_run_id": base_run_id},
    })
    with store.transaction() as conn:
        conn.execute(
            "UPDATE runs SET kind='correction', base_run_id=?, version_no=? WHERE run_id=?",
            (base_run_id, version_no, new_run_id))

    # 2) 输入摘要：基线两份 + 更正文件
    inputs = list(base_inputs) + [{
        "name": table.name, "encoding": table.encoding, "bytes": table.size,
        "sha256": table.sha256, "rows": table.data_rows, "header": table.header,
        "note": "更正补入文件",
    }]
    store.put_inputs(new_run_id, inputs)

    # 3) 订阅：基线全量保留，受影响 sub 用更正记录替换（原结果仍可在版本链查到）
    merged_subs = []
    for sub in store.list_subscriptions(base_run_id):
        merged_subs.append(corrected_records.pop(sub["sub_id"], sub))
    merged_subs.extend(corrected_records.values())
    merged_subs.sort(key=lambda item: item["sub_id"])
    store.put_subscriptions(new_run_id, merged_subs)
    store.put_changes(new_run_id, base_changes)

    # 4) 隔离区整体复制，命中的 error 行标记结案（同一事务，数量不符即抛错回滚）
    with store.transaction() as conn:
        conn.executemany(
            """INSERT INTO quarantine (run_id, file, row_no, code, level, field,
                    raw_value, detail, resolved, resolved_by)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            [(new_run_id, item["file"], int(item["row_no"]), item["code"], item["level"],
              item.get("field", ""), item.get("raw_value", ""), item.get("detail", ""),
              0, "") for item in base_quarantine])
        row_nos = sorted({int(item.quarantine["row_no"]) for item in result.rows})
        sub_file = result.rows[0].quarantine["file"]
        updated = store.mark_quarantine_resolved(
            conn, new_run_id, sub_file, row_nos, release_id)
        if updated != len({(item.quarantine["file"], item.quarantine["row_no"])
                           for item in result.rows}):
            raise Unprocessable("隔离行结案数量与更正条目不符",
                                code="E_CORRECTION_LEDGER")

    # 5) 派生层重算（M5→M4→M6），确定性管线，未受影响账单逐字不变
    change_service.rebuild(store, new_run_id, settings)
    amounts = proration_service.recompute_amounts(store, new_run_id, settings)
    invoices_out = invoice_service.rebuild(store, new_run_id, settings)
    _assert_ledgers_balanced(invoices_out["ledgers"])

    # 6) 计数器与四账：隔离 error 行转为可用，行数账保持可解释且平衡
    counters = dict(base.get("counters", {}))
    n = len(result.rows)
    counters["quarantined_rows"] = int(counters.get("quarantined_rows", 0)) - n
    counters["subs_kept"] = int(counters.get("subs_kept", 0)) + n
    counters["corrected_rows"] = n
    counters["correction_release_id"] = release_id
    store.update_run(new_run_id, counters_json=counters)

    final_invoices = store.list_invoices(new_run_id)
    final_segments = store.list_segments(new_run_id)
    final_components = store.list_components(new_run_id)
    ledgers = reconcile.build(counters=counters, invoices=final_invoices,
                              segments=final_segments, components=final_components)
    _assert_ledgers_balanced(ledgers)
    totals = reconcile.totals(counters, final_invoices, final_segments, final_components)
    totals["segment_exact_total"] = amounts["segment_exact_total"]
    store.put_reconciliations(new_run_id, ledgers)
    store.put_totals(new_run_id, totals)

    stages = _correction_stages(
        base_stages, n, totals,
        f"补入 {n} 行：{', '.join(item.sub_id for item in result.rows)}")
    store.put_stages(new_run_id, stages)

    # 7) 更正条目审计：原结果 / 补入行 / 最终版本三态
    final_by_sub = {row["sub_id"]: row for row in final_invoices}
    entries = []
    for item in result.rows:
        final_inv = final_by_sub.get(item.sub_id)
        entries.append({
            "sub_id": item.sub_id,
            "source_file": item.quarantine["file"],
            "source_row_no": int(item.quarantine["row_no"]),
            "reason_code": item.quarantine["code"],
            "field": item.quarantine.get("field", ""),
            "raw_value": item.quarantine.get("raw_value", ""),
            "base": {
                "quarantine_detail": item.quarantine.get("detail", ""),
                "base_cents": bases[item.sub_id]["base_cents"],
                "had_invoice": bases[item.sub_id]["had_invoice"],
            },
            "corrected": _jsonable(item.record),
            "invoice_id": final_inv["invoice_id"] if final_inv else "",
            "base_cents": bases[item.sub_id]["base_cents"],
            "final_cents": int(final_inv["total_cents"]) if final_inv else 0,
        })
    store.put_correction_entries(release_id, entries)

    finished_at = _now()
    elapsed_ms = int((time.perf_counter() - clock) * 1000)
    digest_all = manifest.digest_parts([inp["sha256"] for inp in inputs])
    manifest_data = manifest.build(
        run_id=new_run_id, batch_key=key, settings=settings, inputs=inputs,
        params={**base.get("params", {}), "correction_file": table.name,
                "base_run_id": base_run_id, "mode": mode},
        started_at=started_at, finished_at=finished_at, elapsed_ms=elapsed_ms,
        stages=stages, counters=counters, totals=totals, reconciliations=ledgers)
    manifest_data["kind"] = "correction"
    manifest_data["base_run_id"] = base_run_id
    manifest_data["version_no"] = version_no
    manifest_data["correction"] = {
        "release_id": release_id,
        "base_run_id": base_run_id,
        "file": table.name,
        "file_sha256": digest,
        "mode": mode,
        "affected_subs": [item.sub_id for item in result.rows],
        "added_invoice_count": len(final_invoices) - len(store.list_invoices(base_run_id)),
        "elapsed_ms": elapsed_ms,
    }
    release_record = {
        "release_id": release_id, "run_id": new_run_id, "base_run_id": base_run_id,
        "root_run_id": root_run_id,
        "batch_key": key, "status": "published", "mode": mode, "file_name": table.name,
        "file_sha256": digest, "created_at": started_at, "published_at": finished_at,
        "affected_subs": [item.sub_id for item in result.rows],
        "added_invoices": [e["invoice_id"] for e in entries if e["invoice_id"]],
        "rejected": [], "note": f"成功补入 {n} 行，四账全平",
    }
    return {
        "finished_at": finished_at,
        "input_digest": digest_all,
        "manifest": manifest_data,
        "release_record": release_record,
    }


def overview(store, run_id: str) -> dict:
    """页面/接口共用：版本链 + 最近发布 + 三态对照。"""
    lineage = store.list_lineage(run_id)
    releases = store.list_correction_releases()
    current = store.get_run(run_id) or {}
    release = None
    entries: list[dict] = []
    if current.get("kind") == "correction":
        release_id = current.get("counters", {}).get("correction_release_id")
        release = store.get_correction_release(release_id) if release_id else None
        if release:
            entries = store.list_correction_entries(release["release_id"])
    return {
        "run_id": run_id,
        "lineage": lineage,
        "releases": releases,
        "current_release": release,
        "entries": entries,
    }


def summary(store, run_id: str, *, reused: bool = False, release_id: str = "") -> dict:
    from ..m1_ingest import service as ingest_service

    run = store.get_run(run_id)
    data = ingest_service.summary(store, run)
    data["reused"] = reused
    data["release_id"] = release_id
    data["kind"] = run.get("kind", "ingest")
    data["base_run_id"] = run.get("base_run_id", "")
    data["version_no"] = run.get("version_no", 1)
    if release_id:
        data["correction_release"] = store.get_correction_release(release_id)
    return data
