from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

STATIC = Path(__file__).parent / "static"
CSP = (
    "default-src 'none'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
    "img-src 'self' data:; connect-src 'self'; form-action 'self'; "
    "base-uri 'none'; frame-ancestors 'none'"
)


def _page(name: str):
    def handler():
        return FileResponse(STATIC / name, headers={"Cache-Control": "no-store"})
    return handler


def setup(app: FastAPI) -> None:
    app.mount("/static", StaticFiles(directory=STATIC), name="static")
    for path, name in (
        ("/", "home.html"),
        ("/login", "login.html"),
        ("/register", "register.html"),
        ("/admin", "admin.html"),
    ):
        app.add_api_route(path, _page(name), methods=["GET"], include_in_schema=False)

    @app.middleware("http")
    async def csp_header(request, call_next):
        resp = await call_next(request)
        resp.headers["Content-Security-Policy"] = CSP
        return resp
