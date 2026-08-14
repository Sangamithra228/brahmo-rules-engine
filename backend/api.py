"""
Transport-independent API layer.

Both entry points - FastAPI (backend/main.py) and the stdlib fallback server
(backend/server.py) - call these functions, so the two can never drift apart
in behaviour. Routing and serialisation differ; the logic does not.
"""

import uuid
from collections import OrderedDict
from typing import Any, Dict, List, Optional

from backend.config import settings
from backend.data.seed_data import KNOWLEDGE_NODES
from backend.derivability.scorer import validate_against_seed
from backend.models import User
from backend.pipeline.bfs_traversal import detect_cycles, traverse
from backend.pipeline.entry_point_resolver import resolve_entry_point
from backend.pipeline.engine import EngineOptions, RulesEngine
from backend.pipeline.permission_compiler import compile_permissions

# Recent runs, so GET /pipeline/{run_id} can return a completed run without
# recomputing it. Bounded - this is a demo cache, not a datastore.
_RUNS: "OrderedDict[str, Dict[str, Any]]" = OrderedDict()
_MAX_RUNS = 50


class ApiError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status
        self.message = message


def options_from(params: Dict[str, Any]) -> EngineOptions:
    def flag(name, default=True):
        v = params.get(name, default)
        if isinstance(v, str):
            return v.lower() not in ("false", "0", "no")
        return bool(v)

    return EngineOptions(
        zone2_enabled=flag("zone2", True),
        derivability_threshold=float(
            params.get("threshold") or settings.derivability_threshold
        ),
        permission_mode=params.get("mode") or settings.permission_mode,
        include_audit=False,
    )


def user_payload(u: User) -> Dict[str, Any]:
    return {
        "id": u.id,
        "name": u.name,
        "role": u.role,
        "department": u.department,
        "org_id": u.org_id,
        "ceiling_level": u.ceiling_level,
        "write_ceiling": u.write_ceiling,
        "compliance_clearance": list(u.compliance_clearance or []),
        "status": u.status,
    }


def health(repo, engine) -> Dict[str, Any]:
    return {
        "status": "ok",
        "database_backend": getattr(repo, "backend_name", "unknown"),
        "configured_backend": settings.backend,
        "org_id": settings.org_id,
        "nodes": repo.total_node_count(settings.org_id),
        "users": len(repo.list_users()),
        "hierarchy_tiers": len(engine.levels()),
        "graph_acyclic": detect_cycles(engine.levels()) == [],
        "llm_calls": 0,
        "embedding_calls": 0,
    }


def list_users(repo) -> List[Dict[str, Any]]:
    return [user_payload(u) for u in repo.list_users()]


def get_user(repo, user_id: str) -> Dict[str, Any]:
    u = repo.get_user(user_id)
    if not u:
        raise ApiError(404, f"no user '{user_id}'")
    return user_payload(u)


def hierarchy(engine) -> List[Dict[str, Any]]:
    return [
        {
            "id": l.id,
            "level_number": l.level_number,
            "level_name": l.level_name,
            "department": l.department,
            "parent_ids": list(l.parent_ids),
            "zone": l.zone,
        }
        for l in engine.levels()
    ]


def _adhoc_user(params: Dict[str, Any]) -> Optional[User]:
    """Build a user that is not in the database.

    This is how a brand-new profile is exercised during the demo without
    touching the schema or the source. The pipeline treats it identically to a
    seeded user, because every rule reads profile fields rather than names.
    """
    if not params.get("role"):
        return None
    clearance = params.get("clearance") or []
    if isinstance(clearance, str):
        clearance = [c.strip() for c in clearance.split(",") if c.strip()]
    wc = params.get("write_ceiling")
    return User(
        id=params.get("id") or "U-ADHOC",
        org_id=params.get("org_id") or settings.org_id,
        name=params.get("name") or "Unseen Profile",
        role=params["role"],
        department=params.get("department") or "general",
        ceiling_level=int(params.get("ceiling") or 10),
        write_ceiling=int(wc) if wc not in (None, "") else None,
        compliance_clearance=clearance,
    )


def resolve_user(repo, params: Dict[str, Any]) -> User:
    uid = params.get("user") or params.get("user_id")
    if uid:
        u = repo.get_user(uid)
        if u:
            return u
        if not params.get("role"):
            raise ApiError(404, f"no user '{uid}'")
    u = _adhoc_user(params)
    if not u:
        raise ApiError(400, "provide 'user', or a role/department/ceiling profile")
    return u


def _traversal_view(engine, user: User) -> Dict[str, Any]:
    """Traversal detail for the DAG panel.

    Structural only: which tiers were reachable and where the walk started.
    It carries no node identities, so it cannot become a side channel that
    reveals what the five checks removed.
    """
    perms = compile_permissions(user)
    entry = resolve_entry_point(perms, engine.levels())
    walk = traverse(entry.level_id, engine.levels())
    org_wide = entry.is_fallback and perms.policy.cross_department_on_fallback

    scope = dict(walk.reachable)
    if org_wide:
        for level in engine.levels():
            scope.setdefault(level.id, max(level.level_number - entry.level_number, 1))

    return {
        "entry_point": entry.level_id,
        "entry_point_name": entry.level_name,
        "entry_reason": entry.reason,
        "ancestor_path": sorted(walk.reachable, key=lambda k: walk.reachable[k]),
        "reachable_levels": sorted(scope.keys()),
        "distances": scope,
        "multi_parent_hits": walk.multi_parent_hits,
        "org_wide_scope": org_wide,
    }


def run_pipeline(repo, engine, params: Dict[str, Any]) -> Dict[str, Any]:
    user = resolve_user(repo, params)
    opts = options_from(params)
    result = engine.run(user, opts)

    payload = result.to_public_dict()
    payload["user_profile"] = user_payload(user)
    payload["options"] = {
        "zone2_enabled": opts.zone2_enabled,
        "derivability_threshold": opts.derivability_threshold,
        "permission_mode": opts.permission_mode,
    }
    payload["traversal"] = _traversal_view(engine, user)
    payload["notes"] = result.notes

    run_id = uuid.uuid4().hex[:12]
    payload["run_id"] = run_id
    _RUNS[run_id] = payload
    while len(_RUNS) > _MAX_RUNS:
        _RUNS.popitem(last=False)
    return payload


def get_run(run_id: str) -> Dict[str, Any]:
    if run_id not in _RUNS:
        raise ApiError(404, f"no run '{run_id}'")
    return _RUNS[run_id]


def compare(repo, engine, user_ids: List[str], params: Dict[str, Any]):
    out = []
    for uid in user_ids:
        u = repo.get_user(uid)
        if u:
            out.append(run_pipeline(repo, engine, dict(params, user=uid)))
    return out


def audit(repo, engine, params: Dict[str, Any]) -> Dict[str, Any]:
    """Operator-only exclusion trail.

    Kept on its own endpoint precisely so the normal pipeline response can
    stay silent. Returns node ids and titles, never content.
    """
    user = resolve_user(repo, params)
    opts = options_from(params)
    opts.include_audit = True
    return engine.run(user, opts).to_audit_dict()


def derivability_report() -> Dict[str, Any]:
    v = validate_against_seed(KNOWLEDGE_NODES, threshold=settings.derivability_threshold)
    return {
        "threshold": v["threshold"],
        "agreement": v["agreement"],
        "total": v["total"],
        "disagreements": v["disagreements"],
        "method": "offline heuristic, batch pre-computation, no LLM or embeddings",
    }
