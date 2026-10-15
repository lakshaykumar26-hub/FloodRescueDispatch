"""FastAPI app factory (Phase 6 Step 01).

One app, thin handlers, CORS open for localhost dashboard dev.
``simulation/`` still imports no FastAPI/DB code: routes call the engine
through ``api.store`` only.
"""

from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from .api import (
    assignments,
    communications,
    events,
    incidents,
    metrics,
    simulations,
    state,
)
from .api.store import ApiError
from .config import from_env, load_dotenv

load_dotenv()


def create_app() -> FastAPI:
    settings = from_env()
    app = FastAPI(title="Flood Rescue Dispatch API")

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.exception_handler(ApiError)
    async def _api_error(_: Request, exc: ApiError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status,
            content={"reason": exc.reason, "message": exc.message},
        )

    @app.get("/health")
    def health() -> dict:
        return {"status": "ok"}

    for module in (
        simulations,
        state,
        incidents,
        assignments,
        events,
        communications,
        metrics,
    ):
        app.include_router(module.router)
    return app


app = create_app()

__all__ = ["app", "create_app"]


if __name__ == "__main__":  # `py -m backend.app.main`: serve with .env settings.
    import uvicorn

    settings = from_env()
    uvicorn.run(
        "backend.app.main:app",
        host=settings.host,
        port=settings.port,
    )
