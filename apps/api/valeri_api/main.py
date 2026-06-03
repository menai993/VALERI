"""VALERI API application factory."""

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse

from valeri_api.api.approvals import router as approvals_router
from valeri_api.api.articles import router as articles_router
from valeri_api.api.auth import router as auth_router
from valeri_api.api.chat import router as chat_router
from valeri_api.api.customers import router as customers_router
from valeri_api.api.dashboard import router as dashboard_router
from valeri_api.api.health import router as health_router
from valeri_api.api.ingest import router as ingest_router
from valeri_api.api.metrics import router as metrics_router
from valeri_api.api.reports import router as reports_router
from valeri_api.api.settings import router as settings_router
from valeri_api.api.signals import router as signals_router
from valeri_api.api.tasks import router as tasks_router


def create_app() -> FastAPI:
    """Build the FastAPI application with all routers mounted under /api."""
    application = FastAPI(title="VALERI API", version="0.1.0")
    application.include_router(health_router, prefix="/api")
    application.include_router(auth_router, prefix="/api")
    application.include_router(ingest_router, prefix="/api")
    application.include_router(tasks_router, prefix="/api")
    application.include_router(reports_router, prefix="/api")
    application.include_router(approvals_router, prefix="/api")
    application.include_router(dashboard_router, prefix="/api")
    application.include_router(metrics_router, prefix="/api")
    application.include_router(customers_router, prefix="/api")
    application.include_router(articles_router, prefix="/api")
    application.include_router(signals_router, prefix="/api")
    application.include_router(settings_router, prefix="/api")
    application.include_router(chat_router, prefix="/api")

    @application.exception_handler(HTTPException)
    async def http_exception_handler(_request: Request, exc: HTTPException) -> JSONResponse:
        """Render errors in the api-spec envelope: {"error": {code, message, details}}."""
        if isinstance(exc.detail, dict):
            code = exc.detail.get("code", str(exc.status_code))
            message = exc.detail.get("message", "")
            details = exc.detail.get("details", {})
        else:
            code = str(exc.status_code)
            message = str(exc.detail)
            details = {}
        return JSONResponse(
            status_code=exc.status_code,
            content={"error": {"code": code, "message": message, "details": details}},
        )

    return application


app = create_app()
