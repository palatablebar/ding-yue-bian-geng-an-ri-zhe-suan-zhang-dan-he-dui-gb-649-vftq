"""应用装配：配置 → 存储 → 模板 → 七个功能模块路由 + 六个页面。

用工厂函数而不是模块级 app：测试可以给每个用例一个临时库和独立样例目录。
"""
from __future__ import annotations

from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from . import config, errors, web
from .modules.m1_ingest import handler as m1_handler
from .modules.m1_ingest import reader
from .modules.m1_ingest import service as ingest_service
from .modules.m2_calendar import handler as m2_handler
from .modules.m2_calendar import service as calendar_service
from .modules.m3_quality import handler as m3_handler
from .modules.m3_quality import service as quality_service
from .modules.m4_proration import handler as m4_handler
from .modules.m4_proration import service as proration_service
from .modules.m5_changes import handler as m5_handler
from .modules.m5_changes import service as change_service
from .modules.m6_invoices import handler as m6_handler
from .modules.m6_invoices import service as invoice_service
from .modules.m7_export import handler as m7_handler
from .store import Store

MODULES = (m1_handler, m2_handler, m3_handler, m4_handler, m5_handler, m6_handler,
           m7_handler)
PAGE_PATHS = ("/", "/subscriptions", "/calendar", "/proration", "/changes", "/invoices")


def _tables(settings, run: dict | None) -> tuple[object, object] | tuple[None, None]:
    """按当前批次的参数重读样例表，用于列契约诊断；读不到就降级为空。"""
    if not run:
        return None, None
    params = run.get("params", {})
    try:
        return (reader.load(settings.sample_dir, params.get("subscriptions")
                            or settings.default_subscriptions),
                reader.load(settings.sample_dir, params.get("changes")
                            or settings.default_changes))
    except Exception:  # noqa: BLE001 - 页面诊断不因样例缺失而 500
        return None, None


def create_app(settings: config.Settings | None = None) -> FastAPI:
    settings = settings or config.Settings.from_env()
    app = FastAPI(
        title="subbill 订阅变更按日折算与账单核对",
        description="采信 → 期间 → 质量 → 变更 → 折算 → 账单",
        version=settings.rule_version,
    )
    app.state.settings = settings
    app.state.store = Store(settings.db_path)
    app.state.ctx = web.Ctx(settings=settings, store=app.state.store)
    web.setup(app)
    app.mount("/static", StaticFiles(directory=str(web.STATIC_DIR)), name="static")
    for module in MODULES:
        app.include_router(module.router)
    errors.install_handlers(app)

    @app.get("/api/health", tags=["平台"])
    def health() -> dict:
        return {
            "status": "ok",
            "rule_version": settings.rule_version,
            "timezone": settings.display_tz,
            "runs": len(app.state.store.list_runs(1)),
        }

    def _render(request: Request, template: str, active: str, **extra):
        ctx = app.state.ctx
        context = web.page_context(ctx, request.query_params.get("run_id"), active)
        context.update(extra)
        return app.state.templates.TemplateResponse(
            request, template, context)

    @app.get("/")
    def page_index(request: Request):
        store = app.state.store
        run = app.state.ctx.current_run(request.query_params.get("run_id"))
        runs = ingest_service.run_rows(store, 12)
        return _render(request, "index.html", "index", runs=runs,
                       sample_subscriptions=settings.default_subscriptions,
                       sample_changes=settings.default_changes,
                       stages=store.list_stages(run["run_id"]) if run else [],
                       ledgers=store.list_reconciliations(run["run_id"]) if run else [],
                       totals=store.list_totals(run["run_id"]) if run else {})

    @app.get("/subscriptions")
    def page_subscriptions(request: Request):
        store = app.state.store
        run = app.state.ctx.current_run(request.query_params.get("run_id"))
        subs = store.list_subscriptions(run["run_id"]) if run else []
        inputs = store.list_inputs(run["run_id"]) if run else []
        quarantine = quality_service.load_quarantine(store, run["run_id"]) if run else {
            "entries": [], "distribution": [], "totals": {"entries": 0}}
        sub_table, change_table = _tables(settings, run)
        maps = ingest_service.header_maps(sub_table, change_table) if sub_table else {}
        return _render(request, "subscriptions.html", "subscriptions",
                       subscriptions=subs, inputs=inputs, maps=maps,
                       quarantine=quarantine)

    @app.get("/calendar")
    def page_calendar(request: Request):
        store = app.state.store
        run = app.state.ctx.current_run(request.query_params.get("run_id"))
        rows = calendar_service.period_rows(store, run["run_id"]) if run else []
        return _render(request, "calendar.html", "calendar", periods=rows,
                       totals=calendar_service.period_totals(rows))

    @app.get("/proration")
    def page_proration(request: Request):
        store = app.state.store
        run = app.state.ctx.current_run(request.query_params.get("run_id"))
        rows = proration_service.segment_rows(store, run["run_id"]) if run else []
        summary = proration_service.summary(store, run["run_id"]) if run else {
            "segments": 0, "invoices": 0, "days": 0, "amount": "0.00"}
        return _render(request, "proration.html", "proration", segments=rows,
                       summary=summary)

    @app.get("/changes")
    def page_changes(request: Request):
        store = app.state.store
        run = app.state.ctx.current_run(request.query_params.get("run_id"))
        rows = change_service.change_rows(store, run["run_id"]) if run else []
        summary = change_service.summary(store, run["run_id"]) if run else {
            "changes": 0, "applied": 0, "superseded": 0, "flagged": 0,
            "components": 0, "credit_rows": 0, "credit_cents": 0}
        return _render(request, "changes.html", "changes", changes=rows, summary=summary)

    @app.get("/invoices")
    def page_invoices(request: Request):
        store = app.state.store
        run = app.state.ctx.current_run(request.query_params.get("run_id"))
        data = invoice_service.overview(store, run["run_id"]) if run else {
            "invoices": [], "ledgers": [], "totals": {}}
        return _render(request, "invoices.html", "invoices", invoices=data["invoices"],
                       ledgers=data["ledgers"], totals=data["totals"])

    def _head_ok() -> Response:
        return Response(status_code=200, media_type="text/html; charset=utf-8")

    for path in (*PAGE_PATHS, "/api/health"):
        app.add_api_route(path, _head_ok, methods=["HEAD"], include_in_schema=False)

    @app.exception_handler(ValueError)
    async def _value_error(request: Request, exc: ValueError):  # noqa: ANN001
        return JSONResponse(status_code=400,
                            content={"error": "E_BAD_REQUEST", "message": str(exc)})

    return app
