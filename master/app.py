import json
import logging
import os
import sqlite3
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import urlsplit

import anyio
from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.middleware.gzip import GZipMiddleware
from starlette.requests import Request
from starlette.responses import FileResponse, JSONResponse
from starlette.routing import Route

from .config import Config
from .database import Database
from .integrations import Integrations
from .security import BusinessError
from .service import Service

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("emby-panel")
MAX_BODY = 64 * 1024


def create_app(config=None, integrations=None, background=True):
    @asynccontextmanager
    async def lifespan(app):
        settings = config or Config.load()
        database = Database(settings.db_file)
        await anyio.to_thread.run_sync(database.initialize)
        app.state.service = Service(settings, database, integrations or Integrations(settings))
        app.state.limiter = anyio.CapacityLimiter(16)
        app.state.auth_limiter = anyio.CapacityLimiter(8)
        if background and os.environ.get("EMBY_BACKGROUND", "1") != "0":
            app.state.service.start()
        yield
        await anyio.to_thread.run_sync(app.state.service.close)

    async def endpoint(request: Request):
        service, path = request.app.state.service, request.url.path
        if path.startswith("/api/"):
            path = path[4:]
        try:
            if request.method == "POST":
                origin = request.headers.get("origin")
                if origin and urlsplit(origin).netloc != request.headers.get("host"):
                    raise BusinessError("Origin rejected", 403)
                raw = bytearray()
                async for chunk in request.stream():
                    raw.extend(chunk)
                    if len(raw) > MAX_BODY:
                        raise BusinessError("Request too large", 413)
                try:
                    data = json.loads(raw)
                    if not isinstance(data, dict):
                        raise ValueError()
                except (ValueError, UnicodeDecodeError):
                    raise BusinessError("Invalid JSON object")
            else:
                data = {}

            def dispatch():
                if path == "/healthz" and request.method == "GET":
                    with service.db.connect() as db:
                        db.execute("SELECT 1 FROM users LIMIT 1").fetchone()
                    return {"ok": True, "version": "2.0.0"}, 200
                if path == "/login" and request.method == "POST":
                    ip = request.headers.get("x-real-ip") or (request.client.host if request.client else "unknown")
                    return service.login(data, ip), 200
                if path == "/worker/bootstrap" and request.method == "POST":
                    return service.bootstrap(data), 200
                # Compatibility for browsers left open during upgrade.
                if path == "/queue/join" and request.method == "POST":
                    return {"ticket": "compat", "position": 0}, 200
                if path == "/queue/status" and request.method == "GET":
                    return {"position": 0, "ready": True}, 200
                token = request.headers.get("authorization", "")
                if token.startswith("Bearer "):
                    token = token[7:]
                session = service.session(token)
                admin = session["role"] == "admin"
                if path == "/logout" and request.method == "POST":
                    with service.db.connect(write=True) as db:
                        db.execute("DELETE FROM sessions WHERE token=?", (token,))
                    return {"msg": "Logged out"}, 200
                if path.startswith("/admin/") and not admin:
                    raise BusinessError("Forbidden", 403)
                if request.method == "GET":
                    if (path == "/admin/data" and admin) or (path == "/user/data" and not admin):
                        return service.data(session), 200
                    if path.startswith("/operations/"):
                        return service.operation(path.rsplit("/", 1)[1], session), 200
                if request.method == "POST":
                    routes = {
                        "/user/add_route": "add", "/user/update_route": "update",
                        "/admin/update_route": "update", "/user/delete_route": "delete",
                        "/admin/delete_route": "delete",
                    }
                    if path in routes:
                        return service.enqueue(routes[path], data, session), 202
                    if path.startswith("/admin/"):
                        return service.admin_action(path, data), 200
                raise BusinessError("Not found", 404)

            limiter = request.app.state.auth_limiter if path == "/login" else request.app.state.limiter
            result, status = await anyio.to_thread.run_sync(dispatch, limiter=limiter)
        except BusinessError as error:
            result, status = {"msg": str(error)}, error.status
        except sqlite3.OperationalError:
            logger.exception("database-request-error")
            result, status = {"msg": "Database temporarily busy; retry shortly"}, 503
        except Exception:
            logger.exception("request-error")
            result, status = {"msg": "Internal error; check master logs"}, 500
        return JSONResponse(result, status, headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"})

    async def frontend(request):
        name = request.path_params.get("file", "index.html")
        if name not in {"index.html", "panel.js", "panel.css", "lucide.min.js"}:
            return JSONResponse({"msg": "Not found"}, 404)
        return FileResponse(Path(__file__).parent / name, headers={
            "Cache-Control": "no-cache", "X-Content-Type-Options": "nosniff",
            "Content-Security-Policy": "default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; img-src 'self' data:; object-src 'none'; base-uri 'self'; frame-ancestors 'none'",
        })

    return Starlette(lifespan=lifespan, middleware=[Middleware(GZipMiddleware, minimum_size=1000)], routes=[
        Route("/", frontend), Route("/panel", frontend), Route("/admin-panel", frontend),
        Route("/assets/{file}", frontend),
        Route("/{path:path}", endpoint, methods=["GET", "POST"]),
    ])


app = create_app()
