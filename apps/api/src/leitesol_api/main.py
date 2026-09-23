from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.utils import get_openapi
from fastapi.responses import JSONResponse
from slowapi.errors import RateLimitExceeded
from starlette.middleware.trustedhost import TrustedHostMiddleware

from leitesol_api.infrastructure.logging import configure_logging
from leitesol_api.infrastructure.settings import get_settings
from leitesol_api.interfaces.http.middlewares.healthcheck import HealthcheckMiddleware
from leitesol_api.interfaces.http.middlewares.logging import LoggingMiddleware
from leitesol_api.interfaces.http.middlewares.security import ApiKeyMiddleware, SecurityHeadersMiddleware
from leitesol_api.interfaces.http.routes.auth import router as auth_router, limiter
from leitesol_api.interfaces.http.routes.chat import router as chat_router
from leitesol_api.interfaces.http.routes.health import router as health_router
from leitesol_api.interfaces.http.routes.key_vault import router as key_vault_router
from leitesol_api.interfaces.http.routes.measures import router as measures_router
from leitesol_api.interfaces.responses import build_response_payload


async def rate_limit_exceeded_handler(request: Request, exc: Exception) -> JSONResponse:
    """Handler customizado para rate limit exceeded."""
    return JSONResponse(
        status_code=429,
        content={
            "detail": "Rate limit exceeded. Maximum 5 requests per minute.",
            "error": "TooManyRequests",
        },
    )


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging()

    app = FastAPI(
        title="LeiteSol API",
        version="0.1.0",
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
        swagger_ui_init_oauth={
            "clientId": "swagger-ui",
            "usePkceWithAuthorizationCodeGrant": False,
        },
    )
    
    # Registrar rate limiter
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, rate_limit_exceeded_handler)

    app.add_middleware(HealthcheckMiddleware)
    app.add_middleware(LoggingMiddleware)
    app.add_middleware(SecurityHeadersMiddleware)
    app.add_middleware(ApiKeyMiddleware)
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=settings.trusted_hosts)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
        payload = build_response_payload(
            data=None,
            message="Unexpected internal error.",
            error=str(exc) if settings.environment != "production" else "Internal server error.",
            status_code=500,
            trace_id=getattr(request.state, "request_id", None),
        )
        return JSONResponse(status_code=500, content=payload)

    app.include_router(auth_router)
    app.include_router(chat_router)
    app.include_router(health_router)
    app.include_router(key_vault_router)
    app.include_router(measures_router)

    # Customizar OpenAPI schema para documentar OAuth2
    def custom_openapi():
        if app.openapi_schema:
            return app.openapi_schema
        openapi_schema = get_openapi(
            title="LeiteSol API",
            version="0.1.0",
            description="API do Agente Comercial LeiteSol com autenticação OAuth2",
            routes=app.routes,
        )
        openapi_schema["components"]["securitySchemes"] = {
            "OAuth2PasswordBearer": {
                "type": "oauth2",
                "flows": {
                    "password": {
                        "tokenUrl": "token",
                        "scopes": {},
                    }
                },
            }
        }
        app.openapi_schema = openapi_schema
        return app.openapi_schema

    app.openapi = custom_openapi

    return app


app = create_app()
