from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from starlette.concurrency import run_in_threadpool
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.middleware.gzip import GZipMiddleware
from starlette.responses import JSONResponse, Response

from backend.app.api.authn import ADMIN_CONTEXT, resolve_user_context
from backend.app.api.router import api_router
from backend.app.config import get_settings
from backend.app.security import decode_access_token


PUBLIC_API_PATHS = {
    "/api/v1/health",
    "/api/v1/health/db",
    "/api/v1/auth/login",
}


class Utf8JsonMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        response = await call_next(request)
        content_type = response.headers.get("content-type", "")
        if content_type.startswith("application/json") and "charset=" not in content_type.lower():
            response.headers["content-type"] = "application/json; charset=utf-8"
        return response


class AdminAuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        settings = get_settings()
        if not settings.auth_enabled or request.method == "OPTIONS" or request.url.path in PUBLIC_API_PATHS:
            request.state.auth = ADMIN_CONTEXT if not settings.auth_enabled else None
            return await call_next(request)

        auth_header = request.headers.get("authorization", "")
        scheme, _, token = auth_header.partition(" ")
        if scheme.lower() != "bearer" or not token:
            return JSONResponse({"detail": "Not authenticated."}, status_code=401)

        # Legacy static admin token: kept as script compatibility and as the
        # recovery path if the admin password is lost.
        if token == settings.effective_admin_token:
            request.state.auth = ADMIN_CONTEXT
            return await call_next(request)

        payload = decode_access_token(token, secret=settings.effective_auth_jwt_secret)
        if payload:
            context = await run_in_threadpool(resolve_user_context, payload)
            if context:
                request.state.auth = context
                return await call_next(request)

        return JSONResponse({"detail": "Not authenticated."}, status_code=401)


def enforce_startup_auth_security(settings) -> None:
    """Log auth misconfigurations; refuse to start when strict mode is on.

    Strict mode is opt-in (AUTH_STRICT=true) or implied by APP_ENV=production,
    so existing deployments keep booting and see the warnings in logs first.
    """
    warnings = settings.auth_security_warnings
    if not warnings:
        return
    if settings.auth_strict_effective:
        raise RuntimeError(
            "Refusing to start with insecure auth configuration:\n- " + "\n- ".join(warnings)
        )
    for warning in warnings:
        print(f"[auth-warning] {warning}", flush=True)


def create_app() -> FastAPI:
    settings = get_settings()
    enforce_startup_auth_security(settings)

    app = FastAPI(
        title=settings.app_name,
        debug=settings.debug,
        version="0.1.0",
    )

    app.add_middleware(Utf8JsonMiddleware)
    app.add_middleware(AdminAuthMiddleware)
    # 后加的更外层：CORS > GZip > AdminAuth > Utf8Json。
    # GZip 必须在 Utf8Json 之外——content-type 先定好，再压缩体。JSON 压缩率约 75%。
    app.add_middleware(GZipMiddleware, minimum_size=500)

    if settings.cors_origin_list:
        allow_credentials = settings.cors_origin_list != ["*"]
        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.cors_origin_list,
            allow_credentials=allow_credentials,
            allow_methods=["*"],
            allow_headers=["*"],
        )

    app.include_router(api_router, prefix="/api/v1")

    @app.get("/")
    def root() -> dict[str, str]:
        return {"app": settings.app_name, "status": "ok"}

    return app


app = create_app()
