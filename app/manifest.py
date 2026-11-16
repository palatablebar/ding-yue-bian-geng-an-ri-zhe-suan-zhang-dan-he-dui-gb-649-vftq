"""运行清单：run_id、校验位、输入摘要、规则版本、参数、耗时。

- ``batch_key`` 只由规则版本与两份输入摘要决定：同输入重跑命中同一批次，不新增行。
- ``run_id`` 用于人读与归档，``check_digit`` 是 mod-97 校验位（清单上印在批次号右侧）。
"""
from __future__ import annotations

import datetime as dt
import hashlib
import uuid
from zoneinfo import ZoneInfo

from . import config


def _expand(text: str) -> str:
    """字母按 A=10…Z=35 展开，只保留字母数字，供 mod-97 计算。"""
    out = []
    for ch in text:
        if ch.isdigit():
            out.append(ch)
        elif ch.isalpha():
            out.append(str(ord(ch.upper()) - 55))
    return "".join(out)


def check_digit(run_id: str) -> str:
    """两位校验位：把 run_id 当账号主体，按 mod-97-10 计算。"""
    remainder = int(_expand(run_id) + "00") % 97
    return f"{98 - remainder:02d}"


def verify_check(run_id: str, check: str) -> bool:
    return bool(check) and int(_expand(run_id + check)) % 97 == 1


def new_run_id(prefix: str = "SB", zone: str = config.DISPLAY_TZ) -> str:
    stamp = dt.datetime.now(ZoneInfo(zone)).strftime("%Y%m%d%H%M%S")
    return f"{prefix}-{stamp}-{uuid.uuid4().hex[:4].upper()}"


def digest_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def digest_parts(parts: list[str]) -> str:
    h = hashlib.sha256()
    for part in parts:
        h.update(part.encode("utf-8"))
        h.update(b"\x00")
    return h.hexdigest()


def batch_key(rule_version: str, digests: list[str]) -> str:
    return digest_parts([rule_version, *digests])[:32]


def build(*, run_id: str, batch_key: str, settings, inputs: list[dict],
          params: dict, started_at: str, finished_at: str, elapsed_ms: int,
          stages: list[dict], counters: dict, totals: dict,
          reconciliations: list[dict]) -> dict:
    return {
        "run_id": run_id,
        "check_digit": check_digit(run_id),
        "batch_key": batch_key,
        "rule_version": settings.rule_version,
        "reused": False,
        "timezone": f"入库 UTC，展示 {settings.display_tz}",
        "money": f"金额 Decimal，单位 {config.MONEY_UNIT}，按分记账（最小刻度 {config.CENT}）",
        "period_rule": "半开区间 [start, end)，天数为本地日历日差",
        "inputs": [
            {
                "name": item["name"],
                "sha256": item["sha256"],
                "bytes": item["bytes"],
                "encoding": item["encoding"],
                "rows": item["rows"],
            }
            for item in inputs
        ],
        "input_digest": digest_parts([item["sha256"] for item in inputs]),
        "params": params,
        "started_at": started_at,
        "finished_at": finished_at,
        "elapsed_ms": elapsed_ms,
        "stages": stages,
        "counters": counters,
        "totals": {key: str(value) for key, value in sorted(totals.items())},
        "reconciliations": reconciliations,
        "replayable": "同 batch_key 重跑复用同一批次，行数与合计不变",
    }
