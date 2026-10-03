"""Application factory.

Run with:  uvicorn sut.app:create_app --factory --port 8000
"""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, Request, status
from fastapi.exception_handlers import http_exception_handler
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from sut import api, db, services, web
from sut.config import Settings

_ERROR_STATUS: dict[type[services.DomainError], int] = {
    services.NotFound: status.HTTP_404_NOT_FOUND,
    services.Conflict: status.HTTP_409_CONFLICT,
    services.InvalidInput: status.HTTP_400_BAD_REQUEST,
    services.AuthError: status.HTTP_401_UNAUTHORIZED,
}


def _wants_html(request: Request) -> bool:
    is_api = request.url.path.startswith("/api/")
    return not is_api and "text/html" in request.headers.get("accept", "")


def _validation_detail(exc: RequestValidationError) -> list[dict[str, object]]:
    """The 422 body without each error's ``input`` and ``ctx`` (BUG-010).

    FastAPI's default handler echoes the rejected input back. A lone surrogate
    (``"\\ud800"``) or a non-finite number (``NaN``, ``1e400``) is exactly what pydantic
    rejects, and it cannot be encoded as UTF-8 JSON, so the error response itself
    crashed with a 500. ``type``, ``loc`` and ``msg`` hold no client data for these
    models (none has dict-keyed fields, and unknown keys are ignored).
    """
    return [{key: error[key] for key in ("type", "loc", "msg")} for error in exc.errors()]


def _error_page(request: Request, template: str, status_code: int) -> Response:
    return web.templates.TemplateResponse(
        request, template, {"user": None}, status_code=status_code
    )


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings.from_env()
    db.initialise(settings.db_path, seed=settings.seed)

    app = FastAPI(title="Bookshop (system under test)", version="1.0.0")
    app.state.settings = settings

    @app.exception_handler(services.DomainError)
    async def domain_error(_: Request, exc: services.DomainError) -> JSONResponse:
        code = _ERROR_STATUS.get(type(exc), status.HTTP_400_BAD_REQUEST)
        return JSONResponse({"detail": str(exc)}, status_code=code)

    # Browsers get HTML error pages instead of raw framework JSON (BUG-003, BUG-004);
    # API clients (and anything under /api/) keep the JSON error contract.
    @app.exception_handler(StarletteHTTPException)
    async def http_error(request: Request, exc: StarletteHTTPException) -> Response:
        if exc.status_code == 404 and _wants_html(request):
            return _error_page(request, "not_found.html", 404)
        return await http_exception_handler(request, exc)

    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, exc: RequestValidationError) -> Response:
        if _wants_html(request):
            return _error_page(request, "bad_request.html", 400)
        return JSONResponse(
            {"detail": _validation_detail(exc)}, status_code=status.HTTP_422_UNPROCESSABLE_CONTENT
        )

    app.mount("/static", StaticFiles(directory=Path(__file__).parent / "static"), name="static")
    app.include_router(api.router)
    app.include_router(web.router)
    return app
