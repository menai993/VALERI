"""VALERI API application factory."""

from fastapi import FastAPI

from valeri_api.api.health import router as health_router


def create_app() -> FastAPI:
    """Build the FastAPI application with all routers mounted under /api."""
    application = FastAPI(title="VALERI API", version="0.1.0")
    application.include_router(health_router, prefix="/api")
    return application


app = create_app()
