"""
FastAPI application - the primary backend for the assessment.

    pip install -r requirements.txt
    uvicorn backend.main:app --reload --port 8000

Database selection is governed by DATABASE_BACKEND (default: supabase).
See backend/config.py. If Supabase is not configured the app refuses to start
rather than silently using SQLite.
"""

import logging
import os
from typing import List, Optional

from fastapi import FastAPI, Header, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from backend import api
from backend.config import get_repository, settings
from backend.pipeline.engine import RulesEngine

log = logging.getLogger("brahmo")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FRONTEND_DIST = os.path.join(ROOT, "frontend", "dist")

app = FastAPI(
    title="BRAHMO Rules Engine",
    description=(
        "Deterministic knowledge-graph filtering. BFS traversal, Zone 2 "
        "injection, five sequential checks. Zero LLM, zero runtime embeddings."
    ),
    version="1.0.0",
)
# A wildcard origin would let any website read the /admin exclusion trail
# from a logged-in browser. Origins are explicit and configurable.
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type", "X-Admin-Token"],
)

repo = get_repository()
engine = RulesEngine(repo, org_id=settings.org_id)


@app.exception_handler(api.ApiError)
async def _api_error(_request, exc: api.ApiError):
    return JSONResponse(status_code=exc.status, content={"detail": exc.message})


@app.exception_handler(Exception)
async def _unhandled(_request, exc: Exception):
    """Log the detail, return none of it.

    A raw exception body can leak SQL fragments, file paths, or the content of
    rows the caller is not cleared to see - which would undo silent exclusion
    through the error channel.
    """
    log.exception("unhandled error", exc_info=exc)
    return JSONResponse(status_code=500, content={"detail": "Internal server error"})


class PipelineRequest(BaseModel):
    user: Optional[str] = None
    zone2: bool = True
    threshold: Optional[float] = None
    mode: Optional[str] = None
    # An unseen profile can be supplied inline instead of a user id.
    role: Optional[str] = None
    department: Optional[str] = None
    ceiling: Optional[int] = None
    write_ceiling: Optional[int] = None
    clearance: Optional[List[str]] = None
    name: Optional[str] = None
    org_id: Optional[str] = None


# ---------------------------------------------------------------- core API
@app.get("/health")
def health():
    return api.health(repo, engine)


@app.get("/users")
def users():
    return api.list_users(repo)


@app.get("/users/{user_id}")
def user(user_id: str):
    return api.get_user(repo, user_id)


@app.get("/hierarchy")
def hierarchy():
    return api.hierarchy(engine)


@app.post("/pipeline/run")
def pipeline_run(body: PipelineRequest):
    return api.run_pipeline(repo, engine, body.model_dump(exclude_none=True))


@app.get("/pipeline/compare")
def pipeline_compare(
    users: str = "U-PRIYA,U-VIKRAM,U-SURESH",
    zone2: bool = True,
    threshold: Optional[float] = None,
    mode: Optional[str] = None,
):
    ids = [u.strip() for u in users.split(",") if u.strip()]
    return api.compare(
        repo, engine, ids,
        {"zone2": zone2, "threshold": threshold, "mode": mode},
    )


@app.get("/pipeline/{run_id}")
def pipeline_get(run_id: str):
    return api.get_run(run_id)


# ------------------------------------------------------- operator endpoints
@app.get("/admin/audit")
def admin_audit(
    request: Request,
    user: str,
    zone2: bool = True,
    x_admin_token: Optional[str] = Header(default=None),
):
    """Explains every exclusion. Gated - see api.require_admin.

    Deliberately separate from /pipeline/run: merging the two would end silent
    exclusion, because a caller could count what was removed. It is gated
    because the trail names the very nodes the pipeline withheld.
    """
    api.require_admin(request.client.host if request.client else None,
                      x_admin_token)
    return api.audit(repo, engine, {"user": user, "zone2": zone2})


@app.get("/admin/derivability")
def admin_derivability(
    request: Request, x_admin_token: Optional[str] = Header(default=None)
):
    api.require_admin(request.client.host if request.client else None,
                      x_admin_token)
    return api.derivability_report()


# ------------------------------------------------------------ static build
if os.path.isdir(FRONTEND_DIST):
    app.mount(
        "/assets",
        StaticFiles(directory=os.path.join(FRONTEND_DIST, "assets")),
        name="assets",
    )

    @app.get("/", include_in_schema=False)
    def index():
        return FileResponse(os.path.join(FRONTEND_DIST, "index.html"))
