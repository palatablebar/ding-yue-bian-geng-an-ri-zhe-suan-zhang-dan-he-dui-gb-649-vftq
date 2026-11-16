"""M8 更正补入 HTTP：发布、幂等、上传、拒绝、页面三态与导出。"""
from __future__ import annotations

import csv
import io
from pathlib import Path

from app.config import Settings

CORRECTION_FILE = "subscriptions_correction.csv"


def _import(client):
    assert client.post("/api/subscriptions/import", json={}).status_code == 200


def test_patch_endpoint_publishes_and_balances(client):
    _import(client)
    resp = client.post("/api/corrections", json={"file": CORRECTION_FILE})
    assert resp.status_code == 200
    data = resp.json()
    assert data["kind"] == "correction"
    assert data["version_no"] == 2
    assert [row["status"] for row in data["ledgers"]] == ["ok"] * 4
    assert data["totals"]["invoices"] == "13"


def test_patch_endpoint_is_idempotent(client):
    _import(client)
    first = client.post("/api/corrections", json={"file": CORRECTION_FILE}).json()
    second = client.post("/api/corrections", json={"file": CORRECTION_FILE}).json()
    assert second["reused"] is True
    assert second["run_id"] == first["run_id"]
    runs = client.get("/api/runs", params={"limit": 50}).json()["runs"]
    assert len(runs) == 2


def test_replace_mode_returns_422(client):
    _import(client)
    resp = client.post("/api/corrections",
                       json={"file": CORRECTION_FILE, "mode": "replace"})
    assert resp.status_code == 422
    assert resp.json()["error"] == "E_CORRECTION_MODE"


def test_multipart_upload_publishes(client):
    _import(client)
    path = Path(Settings().sample_dir) / CORRECTION_FILE
    with path.open("rb") as handle:
        resp = client.post(
            "/api/corrections",
            files={"file": ("uploaded.csv", handle, "text/csv")},
            data={"mode": "patch"})
    assert resp.status_code == 200
    assert resp.json()["totals"]["invoices"] == "13"


def test_invalid_correction_returns_422_with_reasons(client):
    _import(client)
    bad = ("订阅号,账户,套餐,月价(元),期间起,期间止,时区,状态\n"
           "SUB-1001,x,标准版,1200.00,2026-02-01,2026-03-01,+08:00,active\n").encode()
    resp = client.post("/api/corrections",
                       files={"file": ("bad.csv", bad, "text/csv")})
    assert resp.status_code == 422
    body = resp.json()
    assert body["error"] == "E_CORRECTION_INVALID"
    assert body["detail"]["rejected"][0]["code"] == "R_CORRECTION_NO_QUARANTINE"
    # 失败后基线仍是当前版本且账单数不变
    overview = client.get("/api/invoices").json()
    assert overview["totals"]["invoices"] == "10"


def test_corrections_page_renders_three_views(client):
    _import(client)
    data = client.post("/api/corrections",
                       json={"file": CORRECTION_FILE}).json()
    page = client.get("/corrections", params={"run_id": data["run_id"]})
    assert page.status_code == 200
    text = page.text
    assert "版本链" in text
    assert "三态对照" in text
    assert "SUB-1004" in text and "SUB-1014" in text
    assert "原始采信" in text and "更正版本" in text
    # 导航出现更正入口
    assert "/corrections" in text


def test_correction_entries_csv_export(client):
    _import(client)
    data = client.post("/api/corrections",
                       json={"file": CORRECTION_FILE}).json()
    resp = client.get("/api/corrections/entries.csv",
                      params={"run_id": data["run_id"]})
    assert resp.status_code == 200
    assert resp.headers["x-row-count"] == "3"
    rows = list(csv.reader(io.StringIO(resp.text.lstrip("﻿"))))
    assert len(rows) - 1 == 3
    body = {row[0]: row for row in rows[1:]}
    # 列：…10 状态, 11 原账单额(分), 12 最终账单额(分), 13 差额(分), 14 账单号
    assert body["SUB-1004"][11] == "0"
    assert body["SUB-1004"][12] == "90000"


def test_releases_endpoint_lists_attempts(client):
    _import(client)
    client.post("/api/corrections", json={"file": CORRECTION_FILE})
    bad = ("订阅号,账户,套餐,月价(元),期间起,期间止,时区,状态\n"
           "SUB-1001,x,标准版,1200.00,2026-02-01,2026-03-01,+08:00,active\n").encode()
    client.post("/api/corrections", files={"file": ("bad.csv", bad, "text/csv")})
    resp = client.get("/api/corrections/releases")
    statuses = {item["status"] for item in resp.json()["releases"]}
    # 校验前置拒绝不产生发布记录；只有成功的一条
    assert statuses == {"published"}
