"""存储层：老库平滑升级到 M8 版本谱系 schema，不丢数据。"""
from __future__ import annotations

import sqlite3

from app.store import Store


def test_legacy_schema_migrates_without_data_loss(tmp_path):
    path = tmp_path / "legacy.sqlite"
    conn = sqlite3.connect(path)
    # 旧版 runs / quarantine / correction_releases（无 M8 新列）
    conn.executescript(
        """
        CREATE TABLE runs (run_id TEXT PRIMARY KEY, batch_key TEXT NOT NULL,
            status TEXT NOT NULL, source TEXT NOT NULL, rule_version TEXT NOT NULL,
            created_at TEXT NOT NULL, finished_at TEXT, input_digest TEXT NOT NULL DEFAULT '',
            params_json TEXT NOT NULL DEFAULT '{}', counters_json TEXT NOT NULL DEFAULT '{}',
            note TEXT NOT NULL DEFAULT '');
        CREATE TABLE quarantine (run_id TEXT NOT NULL, file TEXT NOT NULL,
            row_no INTEGER NOT NULL, code TEXT NOT NULL, level TEXT NOT NULL,
            field TEXT NOT NULL DEFAULT '', raw_value TEXT NOT NULL DEFAULT '',
            detail TEXT NOT NULL DEFAULT '');
        CREATE TABLE correction_releases (release_id TEXT PRIMARY KEY, run_id TEXT NOT NULL,
            base_run_id TEXT NOT NULL, batch_key TEXT NOT NULL, status TEXT NOT NULL,
            mode TEXT NOT NULL, file_name TEXT NOT NULL, file_sha256 TEXT NOT NULL,
            created_at TEXT NOT NULL, published_at TEXT,
            affected_subs_json TEXT NOT NULL DEFAULT '[]',
            added_invoices_json TEXT NOT NULL DEFAULT '[]',
            rejected_json TEXT NOT NULL DEFAULT '[]', note TEXT NOT NULL DEFAULT '');
        """)
    conn.execute(
        "INSERT INTO runs (run_id,batch_key,status,source,rule_version,created_at) "
        "VALUES ('old-1','k','done','src','v','t')")
    conn.execute(
        "INSERT INTO correction_releases (release_id,run_id,base_run_id,batch_key,status,"
        "mode,file_name,file_sha256,created_at) VALUES "
        "('r1','run-x','run-root','k','published','patch','f.csv','h','t')")
    conn.commit()
    conn.close()

    Store(str(path))  # 触发迁移与补索引

    conn = sqlite3.connect(path)
    run_cols = {r[1] for r in conn.execute("PRAGMA table_info(runs)")}
    q_cols = {r[1] for r in conn.execute("PRAGMA table_info(quarantine)")}
    rel_cols = {r[1] for r in conn.execute(
        "PRAGMA table_info(correction_releases)")}
    assert {"kind", "base_run_id", "version_no"} <= run_cols
    assert {"resolved", "resolved_by"} <= q_cols
    assert "root_run_id" in rel_cols

    # 老数据保留，默认值正确，root 回填为 base
    assert conn.execute(
        "SELECT kind, version_no, base_run_id FROM runs").fetchone() == (
        "ingest", 1, "")
    assert conn.execute(
        "SELECT root_run_id FROM correction_releases").fetchone() == ("run-root",)
    indexes = {r[1] for r in conn.execute(
        "PRAGMA index_list('correction_releases')")}
    assert "idx_correction_digest" in indexes
    conn.close()


def test_reopening_new_db_is_idempotent(tmp_path):
    path = tmp_path / "new.sqlite"
    Store(str(path))
    Store(str(path))  # 再开一次不应因重复列/索引报错
    assert path.exists()
