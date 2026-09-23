from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.agent.router import Router
from app.api.routes.dev import router as dev_router
from app.api.routes.health import router as health_router
from app.api.routes.message import router as message_router
from app.api.routes.turns import router as turns_router
from app.api.websocket.voice import router as voice_router
from app.core.config import Settings
from app.core.logging import configure_logging
from app.core.services import build_services


def create_app(
    settings: Settings | None = None, *, router_override: Router | None = None
) -> FastAPI:
    config = settings or Settings()

    @asynccontextmanager
    async def lifespan(application: FastAPI):
        application.state.services = build_services(config, router_override=router_override)
        yield

    application = FastAPI(title="Voice Router", version="0.1.0", lifespan=lifespan)
    application.state.settings = config
    application.state.voice_connections = 0
    application.add_middleware(
        CORSMiddleware,
        allow_origins=[config.frontend_origin],
        allow_methods=["GET", "POST"],
        allow_headers=["Content-Type"],
    )
    application.include_router(health_router)
    if config.enable_dev_stand:
        application.include_router(dev_router)
    application.include_router(message_router)
    application.include_router(turns_router)
    application.include_router(voice_router)
    return application


app = create_app()


def run() -> None:
    settings = Settings()
    configure_logging()
    uvicorn.run(
        "app.main:app",
        host=settings.backend_host,
        port=settings.backend_port,
        ws_max_size=8192,
        ws_max_queue=16,
    )


if __name__ == "__main__":
    run()
