from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse, Response

from backend.app.api.router import api_router
from backend.app.config import get_settings


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
            return await call_next(request)

        auth_header = request.headers.get("authorization", "")
        scheme, _, token = auth_header.partition(" ")
        if scheme.lower() != "bearer" or token != settings.effective_admin_token:
            return JSONResponse({"detail": "Not authenticated."}, status_code=401)
        return await call_next(request)


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
