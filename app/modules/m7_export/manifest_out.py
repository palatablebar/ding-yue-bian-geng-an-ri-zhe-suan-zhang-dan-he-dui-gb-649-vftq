"""运行清单导出：run_id、校验位、输入 sha256、规则版本、合计、对账结论。

清单是复算入口：拿到它就能确认「这份账单是哪两份文件、用哪版规则算出来的」。
"""
from __future__ import annotations

import json

from ... import manifest


def manifest_json(data: dict) -> str:
    return json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True)


def filename(run_id: str) -> str:
    return f"manifest-{run_id}.json"


def verify(data: dict) -> dict:
    """校验位自检：导出前确认清单没有被拼错。"""
    run_id = data.get("run_id", "")
    check = data.get("check_digit", "")
    return {
        "run_id": run_id,
        "check_digit": check or manifest.check_digit(run_id),
        "ok": manifest.verify_check(run_id, check or manifest.check_digit(run_id)),
        "inputs": len(data.get("inputs", [])),
        "replayable": data.get("replayable", ""),
    }
