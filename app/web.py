"""模板渲染与共享视图上下文：过滤器、导航、当前批次选择。

页面只读 store，不在模板里做业务计算；金额、日期、原因码的统一格式都在这里。
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path
from zoneinfo import ZoneInfo

from fastapi import Request
from fastapi.templating import Jinja2Templates

from . import config, manifest, reasons
from .errors import NotFound

TEMPLATES_DIR = Path(__file__).resolve().parent / "templates"
STATIC_DIR = Path(__file__).resolve().parent / "static"

NAV = (
    ("/", "批次清单", "index"),
    ("/subscriptions", "订阅清单", "subscriptions"),
    ("/calendar", "期间日历", "calendar"),
    ("/proration", "按日折算", "proration"),
    ("/changes", "变更抵扣", "changes"),
    ("/invoices", "账单对账", "invoices"),
)


def now_local(zone: str = config.DISPLAY_TZ) -> dt.datetime:
    return dt.datetime.now(ZoneInfo(zone))


def fmt_money(cents) -> str:
    """分 → 元，两位小数，不带货币符号（单位写在列名里）。"""
    try:
        return f"{Decimal(int(cents)) / 100:.2f}"
    except (TypeError, ValueError, InvalidOperation):
        return "—"


def fmt_amount(text) -> str:
    """Decimal 字符串 → 两位小数；无法解析时原样返回，便于发现异常值。"""
    try:
        return f"{Decimal(str(text)).quantize(config.CENT):.2f}"
    except (InvalidOperation, ValueError, TypeError):
        return str(text)


def fmt_days(value) -> str:
    try:
        return str(int(value))
    except (TypeError, ValueError):
        return "—"


def fmt_local(iso_utc: str, zone: str = config.DISPLAY_TZ) -> str:
    if not iso_utc:
        return "—"
    try:
        moment = dt.datetime.fromisoformat(iso_utc.replace("Z", "+00:00"))
    except ValueError:
        return iso_utc
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=config.UTC)
    return moment.astimezone(ZoneInfo(zone)).strftime("%Y-%m-%d %H:%M:%S")


def short_sha(value: str, keep: int = 12) -> str:
    return (value or "")[:keep]


@dataclass
class Ctx:
    settings: config.Settings
    store: object

    def current_run(self, run_id: str | None = None) -> dict | None:
        if run_id:
            return self.store.get_run(run_id)
        return self.store.latest_run()

    def require_run(self, run_id: str | None = None) -> dict | None:
        return self.current_run(run_id)

    def manifest_of(self, run: dict | None) -> dict:
        if not run:
            return {}
        return self.store.get_manifest(run["run_id"]) or {}

    def check_of(self, run: dict | None) -> str:
        if not run:
            return ""
        data = self.manifest_of(run)
        return data.get("check_digit") or manifest.check_digit(run["run_id"])


def get_ctx(request: Request) -> Ctx:
    return request.app.state.ctx


def run_or_404(request: Request, run_id: str | None = None) -> dict:
    """取当前批次：显式 run_id 优先，其次最近一批；都没有就 404 而不是空页。"""
    run = request.app.state.ctx.require_run(run_id or request.query_params.get("run_id"))
    if run is None:
        raise NotFound("还没有批次，先在首页采信一次", code="E_NO_RUN")
    return run


def page_context(ctx: Ctx, run_id: str | None, active: str) -> dict:
    run = ctx.require_run(run_id)
    return {
        "run": run,
        "run_id": run["run_id"] if run else "",
        "check_digit": ctx.check_of(run),
        "active": active,
        "nav": NAV,
        "has_run": bool(run),
        "stage_labels": config.STAGE_LABELS,
        "stage_flow": config.STAGE_FLOW,
        "state_labels": config.STATE_LABELS,
        "kind_labels": config.KIND_LABELS,
        "invoice_status_labels": config.INVOICE_STATUS_LABELS,
        "run_status_labels": config.RUN_STATUS_LABELS,
        "money_unit": config.MONEY_UNIT,
        "column_labels": {
            **{key: label for key, (label, _) in config.SUB_COLUMNS.items()},
            **{key: label for key, (label, _) in config.CHANGE_COLUMNS.items()},
        },
        "timezone_label": ctx.settings.display_tz,
        "generated_at": now_local(ctx.settings.display_tz).strftime("%Y-%m-%d %H:%M:%S"),
        "reason_labels": {code: label for code, (_, label) in reasons.REASONS.items()},
        "reason_levels": {code: level for code, (level, _) in reasons.REASONS.items()},
        "level_labels": reasons.LEVEL_LABELS,
    }


def setup(app) -> None:
    t = Jinja2Templates(directory=str(TEMPLATES_DIR))
    env = t.env
    env.filters["money"] = fmt_money
    env.filters["amount"] = fmt_amount
    env.filters["days"] = fmt_days
    env.filters["local"] = fmt_local
    env.filters["sha"] = short_sha
    env.filters["reason"] = reasons.label_of
    env.filters["level"] = reasons.level_of
    env.filters["level_label"] = lambda code: reasons.LEVEL_LABELS.get(
        reasons.level_of(code), code)
    env.filters["state"] = lambda s: config.STATE_LABELS.get(s, s or "—")
    env.filters["kind"] = lambda k: config.KIND_LABELS.get(k, k or "—")
    env.filters["invoice_status"] = lambda s: config.INVOICE_STATUS_LABELS.get(s, s or "—")
    env.filters["run_status"] = lambda s: config.RUN_STATUS_LABELS.get(s, s or "—")
    env.filters["flags"] = lambda items: [reasons.label_of(code) for code in (items or [])]
    env.filters["flag_codes"] = lambda items: list(items or [])
    app.state.templates = t
