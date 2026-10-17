import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from starlette.datastructures import MutableHeaders
from starlette.exceptions import HTTPException

from . import config, db, security
from .deps import LoginRequired, RedirectTo, login_url
from .events import broker
from .routes import api, auth, catalog, households, lists, meals, plan, recipes, stores
from .templating import render, templates


@asynccontextmanager
async def lifespan(app):
    if db.engine is None:
        db.init_engine()
    broker.bind_loop(asyncio.get_running_loop())
    yield


class SessionCookieRefresh:
    """Re-send the session cookie when its server-side expiry slid forward (see deps._session)."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)

        async def send_wrapper(message):
            if message["type"] == "http.response.start":
                token = scope.get("state", {}).get("refresh_session_token")
                headers = MutableHeaders(scope=message)
                already = any(v.startswith(config.SESSION_COOKIE + "=") for v in headers.getlist("set-cookie"))
                if token and not already:  # e.g. logout/login set their own cookie
                    headers.append("set-cookie", security.session_cookie_header(token))
            await send(message)

        await self.app(scope, receive, send_wrapper)


app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
app.add_middleware(SessionCookieRefresh)
app.mount("/static", StaticFiles(directory=str(config.BASE_DIR / "static")), name="static")

for module in (api, auth, households, lists, stores, catalog, recipes, plan, meals):
    app.include_router(module.router)


def _redirect(request: Request, url):
    if request.headers.get("HX-Request"):
        return HTMLResponse("", headers={"HX-Redirect": url})
    return RedirectResponse(url, status_code=303)


@app.exception_handler(LoginRequired)
async def _login_required(request: Request, exc: LoginRequired):
    return _redirect(request, login_url(exc.next_url))


@app.exception_handler(RedirectTo)
async def _redirect_to(request: Request, exc: RedirectTo):
    return _redirect(request, exc.url)


@app.exception_handler(HTTPException)
async def _http_error(request: Request, exc: HTTPException):
    message = exc.detail if isinstance(exc.detail, str) else "Something went wrong."
    if request.url.path.startswith("/api/"):
        return JSONResponse({"detail": message}, status_code=exc.status_code, headers=getattr(exc, "headers", None))
    if request.headers.get("HX-Request"):
        # Shown by app.js as a toast.
        return HTMLResponse(message, status_code=exc.status_code)
    return render(request, "error.html", {"message": message, "status": exc.status_code}, status_code=exc.status_code)


# The service worker must be served from the root to look after every page (static/sw.js).
_SW_SOURCE = (config.BASE_DIR / "static" / "sw.js").read_text()


@app.get("/sw.js", include_in_schema=False)
def service_worker():
    body = _SW_SOURCE.replace("__VERSION__", templates.env.globals["static_v"])
    return Response(body, media_type="text/javascript", headers={"Cache-Control": "no-cache"})


@app.get("/offline", include_in_schema=False)
def offline_page(request: Request):
    """Shown by the service worker for a page that isn't saved on this device."""
    return templates.TemplateResponse(request, "offline.html", {})


@app.get("/healthz", include_in_schema=False)
def healthz():
    return {"ok": True}
