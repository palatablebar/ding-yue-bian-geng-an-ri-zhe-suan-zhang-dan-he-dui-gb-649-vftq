"""测试夹具：固定时区、临时库、一次完整采信。

时间相关断言全部用固定日期，不读 ``datetime.now()``；
样例目录指向仓库自带的 ``sample_data/``，走与容器完全相同的代码路径。
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ.setdefault("TZ", "Asia/Shanghai")
# 期望值与 CSV 夹具放在 tests/fixtures/，直接按模块名导入
sys.path.insert(0, str(Path(__file__).resolve().parent / "fixtures"))

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app import config  # noqa: E402
from app.main import create_app  # noqa: E402
from app.modules.m1_ingest import service as ingest_service  # noqa: E402
from app.store import Store  # noqa: E402


@pytest.fixture()
def settings(tmp_path) -> config.Settings:
    return config.Settings(db_path=str(tmp_path / "subbill.sqlite"))


@pytest.fixture()
def store(settings) -> Store:
    return Store(settings.db_path)


@pytest.fixture()
def client(settings):
    app = create_app(settings)
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture()
def seeded_client(client) -> TestClient:
    """先走一次采信，再用于只读接口断言。"""
    response = client.post("/api/subscriptions/import", json={})
    assert response.status_code == 200
    return client


@pytest.fixture()
def run_data(store, settings) -> dict:
    return ingest_service.import_sample(store, settings)


@pytest.fixture()
def run_id(run_data) -> str:
    return run_data["run_id"]


@pytest.fixture()
def sample_dir() -> str:
    return config.Settings().sample_dir
