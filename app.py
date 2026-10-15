from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles

from server.config import DEFAULT_PERSONA, persona_var
from server.db import pool
from server.routes import router

DIST = Path(__file__).resolve().parent / "frontend" / "dist"


@asynccontextmanager
async def lifespan(app: FastAPI):
    if pool is not None:
        try:
            pool.open(wait=True, timeout=30.0)
        except Exception as exc:  # noqa: BLE001
            print(f"Lakebase pool open failed: {exc}")
    yield
    if pool is not None:
        pool.close()


app = FastAPI(title="DOL UI Claims Integrity", lifespan=lifespan)


@app.middleware("http")
async def persona_scope(request: Request, call_next):
    token = persona_var.set(request.headers.get("X-DOL-Persona") or DEFAULT_PERSONA)
    try:
        return await call_next(request)
    finally:
        persona_var.reset(token)


app.include_router(router, prefix="/api")

if (DIST / "assets").is_dir():
    app.mount("/assets", StaticFiles(directory=DIST / "assets"), name="assets")


@app.get("/{full_path:path}", response_model=None)
def spa(full_path: str):
    if full_path.startswith("api/"):
        return HTMLResponse("Not found", status_code=404)
    index = DIST / "index.html"
    if index.is_file():
        return FileResponse(index, media_type="text/html", headers={"Cache-Control": "no-cache"})
    return HTMLResponse("<h1>DOL UI Claims</h1><p>frontend/dist is missing from the deployment.</p>", status_code=500)
