from __future__ import annotations

import time
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.requests import Request

from .config import get_settings
from .logging_utils import configure_logging, get_api_logger
from .redaction_jobs import get_redaction_runtime_status
from .routes.auth import router as auth_router
from .routes.cases import router as cases_router
from .routes.documents import router as documents_router
from .routes.files import router as files_router
from .routes.health import router as health_router
from .routes.redactions import router as redactions_router
from .storage import get_object_store_status
from .zkpt_runtime import check_zkpt_readiness


def _is_local_host_value(value: str | None) -> bool:
    if not value:
        return False
    lowered = value.lower()
    return "localhost" in lowered or "127.0.0.1" in lowered


def _validate_startup_contract() -> None:
    settings = get_settings()
    if settings.app_env != "production":
        return

    if settings.debug:
        raise RuntimeError("Production startup blocked: debug mode must be disabled")
    if settings.enable_test_auth:
        raise RuntimeError("Production startup blocked: test auth must be disabled")
    if settings.secret_key == "dev-secret-change-me":
        raise RuntimeError("Production startup blocked: default secret key must be replaced")
    if any(_is_local_host_value(origin) for origin in settings.cors_origins):
        raise RuntimeError("Production startup blocked: localhost CORS origins are not allowed")
    if _is_local_host_value(settings.frontend_origin_regex):
        raise RuntimeError("Production startup blocked: localhost CORS origin regex is not allowed")
    if _is_local_host_value(settings.siwe_domain) or _is_local_host_value(settings.siwe_uri):
        raise RuntimeError("Production startup blocked: SIWE domain and URI must not use localhost")
    if settings.storage_backend.strip().lower() != "s3":
        raise RuntimeError("Production startup blocked: object storage backend must be s3")

    storage_runtime = get_object_store_status()
    if not storage_runtime["ready"]:
        detail = storage_runtime["error"] or "unknown object storage error"
        raise RuntimeError(f"Production startup blocked: object storage runtime is not ready ({detail})")

    zkpt_runtime = check_zkpt_readiness()
    if not zkpt_runtime["ready"]:
        detail = "; ".join(str(item) for item in zkpt_runtime["errors"]) or "unknown ZKPT runtime error"
        raise RuntimeError(f"Production startup blocked: authoritative ZKPT runtime is not ready ({detail})")

    redaction_runtime = get_redaction_runtime_status()
    if not redaction_runtime["ready"]:
        raise RuntimeError("Production startup blocked: redaction runtime is not ready")
    if redaction_runtime["redaction_engine_mode"] != "rust_cli":
        raise RuntimeError("Production startup blocked: redaction engine must be rust_cli")


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging()
    _validate_startup_contract()

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        get_object_store_status()
        check_zkpt_readiness()
        get_redaction_runtime_status(force_refresh=True)
        yield

    app = FastAPI(title=settings.app_name, version="0.1.0", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_origin_regex=settings.frontend_origin_regex,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=[
            "X-BlockVault-Original-Name",
            "X-BlockVault-Content-Type",
            "X-BlockVault-Algorithm",
            "X-BlockVault-Salt",
            "X-BlockVault-Iv",
            "X-Request-Id",
        ],
    )

    @app.middleware("http")
    async def request_logging_middleware(request: Request, call_next):
        logger = get_api_logger()
        request_id = request.headers.get("x-request-id") or str(uuid.uuid4())
        started = time.perf_counter()
        response = None
        try:
            response = await call_next(request)
            return response
        finally:
            duration_ms = round((time.perf_counter() - started) * 1000, 3)
            client = request.client.host if request.client and request.client.host else "unknown"
            status_code = response.status_code if response is not None else 500
            if response is not None:
                response.headers["X-Request-Id"] = request_id
            logger.info(
                "request.completed",
                extra={
                    "structured": {
                        "event": "request.completed",
                        "requestId": request_id,
                        "method": request.method,
                        "path": request.url.path,
                        "query": request.url.query,
                        "clientIp": client,
                        "statusCode": status_code,
                        "durationMs": duration_ms,
                    }
                },
            )

    app.include_router(health_router)
    app.include_router(auth_router)
    app.include_router(files_router)
    app.include_router(cases_router)
    app.include_router(documents_router)
    app.include_router(redactions_router)
    return app


app = create_app()
