from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from starlette.concurrency import run_in_threadpool
from starlette.middleware.base import BaseHTTPMiddleware
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


def create_app() -> FastAPI:
    settings = get_settings()

    app = FastAPI(
        title=settings.app_name,
        debug=settings.debug,
        version="0.1.0",
    )

    app.add_middleware(Utf8JsonMiddleware)
    app.add_middleware(AdminAuthMiddleware)

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
