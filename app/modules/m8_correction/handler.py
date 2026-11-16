"""M8 路由：发布更正、版本链与三态对照、更正条目导出。"""
from __future__ import annotations

import csv
import io

from fastapi import APIRouter, Request, Response, UploadFile

from ... import web
from ...errors import BadRequest
from . import service

router = APIRouter(prefix="/api", tags=["M8 更正补入"])

CORRECTION_HEADER = ["订阅号", "原文件", "原行号", "原因码", "原值", "更正套餐",
                     "更正月价(元)", "更正期间起", "更正期间止", "更正时区", "更正状态",
                     "原账单额(分)", "最终账单额(分)", "差额(分)", "最终账单号"]


@router.post("/corrections")
async def publish(request: Request) -> dict:
    """定向补入发布。

    两种给法：multipart 上传文件（字段 file），或 JSON 指定样例目录里的文件名。
    mode 只接受 patch；replace 明确拒绝（不允许改写已确认结果）。
    """
    settings = request.app.state.settings
    store = request.app.state.store
    content_type = request.headers.get("content-type", "")
    if content_type.startswith("multipart/form-data"):
        form = await request.form()
        mode = str(form.get("mode", "patch"))
        base_run_id = form.get("run_id")
        upload = None
        for key in form:
            value = form[key]
            if isinstance(value, UploadFile) or hasattr(value, "read"):
                upload = value
                break
        if upload is None:
            raise BadRequest("multipart 请求缺少 file 字段", code="E_CORRECTION_EMPTY")
        data = service.publish_correction(
            store, settings, base_run_id=base_run_id,
            file_name=upload.filename or "correction.csv",
            content=await upload.read(), mode=mode)
        return data

    payload = await request.json()
    mode = str(payload.get("mode", "patch"))
    file_name = payload.get("file") or payload.get("subscriptions") or ""
    if not isinstance(file_name, str) or not file_name.strip():
        raise BadRequest("需要更正文件名或上传文件", code="E_CORRECTION_EMPTY")
    data = service.publish_correction(
        store, settings, base_run_id=payload.get("run_id"),
        file_name=file_name.strip(), content=None, mode=mode)
    return data


@router.get("/corrections")
def corrections(request: Request) -> dict:
    run = web.run_or_404(request)
    return service.overview(request.app.state.store, run["run_id"])


@router.get("/corrections/releases")
def releases(request: Request) -> dict:
    store = request.app.state.store
    items = store.list_correction_releases()
    return {"total": len(items), "releases": items}


@router.get("/corrections/entries.csv")
def entries_csv(request: Request) -> Response:
    run = web.run_or_404(request)
    store = request.app.state.store
    data = service.overview(store, run["run_id"])
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(CORRECTION_HEADER)
    for item in data["entries"]:
        corrected = item.get("corrected", {})
        writer.writerow([
            item["sub_id"], item["source_file"], item["source_row_no"],
            item["reason_code"], item.get("raw_value", ""),
            corrected.get("plan", ""), str(corrected.get("monthly", "")),
            corrected.get("period_start", ""), corrected.get("period_end", ""),
            corrected.get("tz", ""), corrected.get("state", ""),
            item["base_cents"], item["final_cents"],
            item["final_cents"] - item["base_cents"], item.get("invoice_id", ""),
        ])
    body = "﻿" + buffer.getvalue()
    return Response(
        content=body, media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition":
                 f'attachment; filename="corrections-{run["run_id"]}.csv"',
                 "X-Row-Count": str(len(data["entries"]))})
