"""
FastAPI application - the stack the assessment specifies.

Identical routes and identical engine to `backend/server.py`; that one exists
so the demo can run with zero installs. Use whichever you prefer:

    pip install -r requirements.txt
    uvicorn backend.main:app --reload --port 8000

    # or, no dependencies at all:
    python3 -m backend.server 8000
"""

import os

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

from backend.data.seed_data import KNOWLEDGE_NODES
from backend.derivability.scorer import validate_against_seed
from backend.models import User
from backend.pipeline.bfs_traversal import detect_cycles
from backend.pipeline.engine import EngineOptions, RulesEngine
from backend.repository.sqlite_repo import SQLiteRepository

FRONTEND = os.path.join(os.path.dirname(os.path.dirname(__file__)), "frontend")

app = FastAPI(
    title="BRAHMO Rules Engine",
    description="BFS traversal + 5-check filter pipeline. Zero LLM.",
    version="1.0.0",
)
app.add_middleware(
    CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"]
)

# Swap this line for SupabaseRepository() to run against Postgres.
repo = SQLiteRepository()
repo.initialise()
repo.seed()
engine = RulesEngine(repo)


def _opts(zone2: bool, threshold: float, mode: str, audit: bool = False):
    return EngineOptions(
        zone2_enabled=zone2,
        derivability_threshold=threshold,
        permission_mode=mode,
        include_audit=audit,
    )


@app.get("/", include_in_schema=False)
def index():
    return FileResponse(os.path.join(FRONTEND, "index.html"))


@app.get("/health")
def health():
    return {
        "status": "ok",
        "nodes": repo.total_node_count("supra"),
        "users": len(repo.list_users()),
        "graph_acyclic": detect_cycles(engine.levels()) == [],
        "llm_calls": 0,
    }


@app.get("/api/users")
def users():
    return [vars(u) for u in repo.list_users()]


@app.get("/api/hierarchy")
def hierarchy():
    return [vars(l) for l in engine.levels()]


@app.get("/api/pipeline")
def pipeline(
    user: str = Query(None),
    zone2: bool = True,
    threshold: float = 0.7,
    mode: str = "strict",
    role: str = None,
    department: str = None,
    ceiling: int = 10,
    name: str = "Ad-hoc User",
    clearance: str = "",
):
    """Run the pipeline. Pass `user` for a seeded profile, or role/department/
    ceiling/clearance to push an unseen profile through without writing it to
    the database - which is how the surprise-user test is demonstrated live."""
    u = repo.get_user(user) if user else None
    if u is None and role:
        u = User(
            id="U-ADHOC", org_id="supra", name=name, role=role,
            department=department or "ortho", ceiling_level=ceiling,
            write_ceiling=None,
            compliance_clearance=[c for c in clearance.split(",") if c],
        )
    if u is None:
        raise HTTPException(404, "unknown user")

    res = engine.run(u, _opts(zone2, threshold, mode))
    payload = res.to_public_dict()
    payload["_demo"] = {"notes": res.notes}
    return payload


@app.get("/api/compare")
def compare(users: str = "U-PRIYA,U-VIKRAM,U-SURESH", zone2: bool = True,
            threshold: float = 0.7, mode: str = "strict"):
    out = []
    for uid in [x.strip() for x in users.split(",") if x.strip()]:
        u = repo.get_user(uid)
        if u:
            out.append(engine.run(u, _opts(zone2, threshold, mode)).to_public_dict())
    return out


@app.get("/api/audit")
def audit(user: str, zone2: bool = True, threshold: float = 0.7,
          mode: str = "strict"):
    """Operator-only. Explains every exclusion.

    Deliberately a SEPARATE endpoint: merging this into /api/pipeline would
    destroy silent exclusion, because the caller could count what was removed.
    In production this sits behind an operator role and writes to audit_log.
    """
    u = repo.get_user(user)
    if not u:
        raise HTTPException(404, "unknown user")
    return engine.run(u, _opts(zone2, threshold, mode, audit=True)).to_audit_dict()


@app.get("/api/derivability")
def derivability():
    v = validate_against_seed(KNOWLEDGE_NODES)
    return {
        "threshold": v["threshold"],
        "agreement": v["agreement"],
        "total": v["total"],
        "disagreements": v["disagreements"],
    }
