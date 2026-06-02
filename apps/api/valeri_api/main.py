"""VALERI API application factory."""

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse

from valeri_api.api.health import router as health_router
from valeri_api.api.ingest import router as ingest_router


def create_app() -> FastAPI:
    """Build the FastAPI application with all routers mounted under /api."""
    application = FastAPI(title="VALERI API", version="0.1.0")
    application.include_router(health_router, prefix="/api")
    application.include_router(ingest_router, prefix="/api")

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
