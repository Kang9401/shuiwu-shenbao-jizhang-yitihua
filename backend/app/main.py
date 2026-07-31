from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import Dict

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.api import artifacts, bank_fetch, files, finance_ai, jobs, ledgers, organization_mappings, periods, personnel_masters, reconciliation_imports, rpa, system, tax, workflows
from app.core.config import settings
from app.core.logging import configure_logging
from app.core.version import APP_VERSION
from app.db.init_db import init_db
from app.rpa.service import rpa_service


@asynccontextmanager
async def lifespan(_app: FastAPI):
    init_db()
    rpa_service.initialize()
    try:
        yield
    finally:
        rpa_service.shutdown()


def create_app() -> FastAPI:
    configure_logging()
    app = FastAPI(title=settings.app_name, version=APP_VERSION, lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.allow_origins_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(periods.router, prefix=settings.api_prefix)
    app.include_router(files.router, prefix=settings.api_prefix)
    app.include_router(jobs.router, prefix=settings.api_prefix)
    app.include_router(artifacts.router, prefix=settings.api_prefix)
    app.include_router(ledgers.router, prefix=settings.api_prefix)
    app.include_router(personnel_masters.router, prefix=settings.api_prefix)
    app.include_router(organization_mappings.router, prefix=settings.api_prefix)
    app.include_router(reconciliation_imports.router, prefix=settings.api_prefix)
    app.include_router(bank_fetch.router, prefix=settings.api_prefix)
    app.include_router(workflows.router, prefix=settings.api_prefix)
    app.include_router(tax.router, prefix=settings.api_prefix)
    app.include_router(system.router, prefix=settings.api_prefix)
    app.include_router(rpa.router, prefix=settings.api_prefix)
    app.include_router(finance_ai.router, prefix=settings.api_prefix)

    @app.get("/health")
    def health() -> Dict[str, str]:
        return {"status": "ok", "version": APP_VERSION}

    @app.exception_handler(Exception)
    async def unhandled_exception(_request, exc: Exception) -> JSONResponse:
        logging.getLogger("app").exception("Unhandled application error", exc_info=exc)
        return JSONResponse(status_code=500, content={"detail": "程序发生未处理错误，请导出诊断包"})

    if settings.frontend_dist_dir.is_dir():
        app.mount("/", StaticFiles(directory=settings.frontend_dist_dir, html=True), name="frontend")

    return app


app = create_app()
