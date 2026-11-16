"""M7 运行清单：run_id + 输入 sha256、校验位、重跑不变、合计一致。"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import expected
from app import manifest
from app.modules.m1_ingest import service as ingest_service


def test_manifest_keys_and_digest(run_id, store, sample_dir):
    data = store.get_manifest(run_id)
    assert data["run_id"] == run_id
    assert data["check_digit"] == manifest.check_digit(run_id)
    assert data["rule_version"] == "subbill/1.0.0"
    names = [item["name"] for item in data["inputs"]]
    assert names == ["subscriptions_dirty.csv", "changes_dirty.csv"]
    for item in data["inputs"]:
        payload = (Path(sample_dir) / item["name"]).read_bytes()
        assert item["sha256"] == hashlib.sha256(payload).hexdigest()
        assert item["bytes"] == len(payload)
    assert data["totals"]["invoice_cents"] == str(expected.TOTAL_CENTS)
    assert len(data["reconciliations"]) == 4


def test_check_digit_roundtrip():
    for run_id in ("SB-20261116010101-AAAA", "SB-20280229000000-0F0F"):
        check = manifest.check_digit(run_id)
        assert len(check) == 2 and check.isdigit()
        assert manifest.verify_check(run_id, check)
        assert not manifest.verify_check(run_id, "00" if check != "00" else "01")


def test_manifest_json_endpoint(seeded_client, run_id):
    response = seeded_client.get("/api/export/manifest.json")
    assert response.status_code == 200
    payload = json.loads(response.text)
    assert payload["run_id"] == run_id
    assert len(payload["input_digest"]) == 64
    assert len(payload["inputs"]) == 2
    assert response.headers["content-type"].startswith("application/json")


def test_manifest_replay_stable(store, settings, run_data):
    same = ingest_service.import_sample(store, settings)
    first = store.get_manifest(run_data["run_id"])
    assert same["reused"] is True
    assert same["totals"]["invoice_cents"] == first["totals"]["invoice_cents"]
    assert same["totals"]["segments"] == first["totals"]["segments"]
    assert store.get_manifest(same["run_id"]) == first


def test_manifest_records_replayable(store, run_id):
    data = store.get_manifest(run_id)
    assert "batch_key" in data and len(data["batch_key"]) == 32
    assert data["stages"] and len(data["stages"]) == 6
    assert data["replayable"].startswith("同 batch_key")
