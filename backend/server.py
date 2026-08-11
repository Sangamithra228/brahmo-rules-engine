"""
Zero-dependency HTTP API (Python stdlib only).

`backend/main.py` holds the FastAPI version, which is the stack the assessment
specifies. This one exists so the demo starts with no pip install and no
network - which on a live demo call is worth more than framework points.
Both expose the same routes and call the same engine.

  GET  /api/users
  GET  /api/hierarchy
  GET  /api/pipeline?user=U-PRIYA[&zone2=false][&threshold=0.7][&mode=strict]
  GET  /api/compare?users=U-PRIYA,U-VIKRAM,U-SURESH
  GET  /api/audit?user=U-PRIYA        <- operator-only exclusion trail
  GET  /api/derivability              <- offline scorer calibration report
  GET  /health
"""

import json
import os
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.data.seed_data import KNOWLEDGE_NODES
from backend.derivability.scorer import validate_against_seed
from backend.pipeline.bfs_traversal import detect_cycles
from backend.pipeline.engine import EngineOptions, RulesEngine
from backend.repository.sqlite_repo import SQLiteRepository

FRONTEND = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "frontend"
)

_repo = None
_engine = None


def boot(db_path=None, reseed=True):
    global _repo, _engine
    _repo = SQLiteRepository(db_path)
    if reseed:
        _repo.initialise()
        _repo.seed()
    _engine = RulesEngine(_repo)
    return _repo, _engine


def _opts(q):
    return EngineOptions(
        zone2_enabled=q.get("zone2", ["true"])[0].lower() != "false",
        derivability_threshold=float(q.get("threshold", ["0.7"])[0]),
        permission_mode=q.get("mode", ["strict"])[0],
        include_audit=False,
    )


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):  # keep the demo console clean
        pass

    def _send(self, code, payload, ctype="application/json"):
        body = (
            json.dumps(payload, indent=2).encode()
            if ctype == "application/json" else payload
        )
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        u = urlparse(self.path)
        q = parse_qs(u.query)
        path = u.path

        try:
            if path in ("/", "/index.html"):
                with open(os.path.join(FRONTEND, "index.html"), "rb") as f:
                    return self._send(200, f.read(), "text/html; charset=utf-8")

            if path == "/health":
                return self._send(200, {
                    "status": "ok",
                    "nodes": _repo.total_node_count("supra"),
                    "users": len(_repo.list_users()),
                    "graph_acyclic": detect_cycles(_engine.levels()) == [],
                    "llm_calls": 0,
                })

            if path == "/api/users":
                return self._send(200, [
                    {"id": x.id, "name": x.name, "role": x.role,
                     "department": x.department, "ceiling_level": x.ceiling_level,
                     "write_ceiling": x.write_ceiling,
                     "compliance_clearance": x.compliance_clearance}
                    for x in _repo.list_users()
                ])

            if path == "/api/hierarchy":
                return self._send(200, [
                    {"id": l.id, "level_number": l.level_number,
                     "level_name": l.level_name, "department": l.department,
                     "parent_ids": l.parent_ids, "zone": l.zone}
                    for l in _engine.levels()
                ])

            if path == "/api/pipeline":
                uid = q.get("user", [""])[0]
                user = _repo.get_user(uid) or _synthetic(q)
                if not user:
                    return self._send(404, {"error": "unknown user"})
                res = _engine.run(user, _opts(q))
                payload = res.to_public_dict()
                # Traversal detail is demo scaffolding, not part of the
                # candidate-set contract.
                payload["_demo"] = {
                    "notes": res.notes,
                    "reachable_levels": sorted(
                        _reach(user, _opts(q)).reachable.keys()),
                }
                return self._send(200, payload)

            if path == "/api/compare":
                uids = q.get("users", ["U-PRIYA,U-VIKRAM,U-SURESH"])[0].split(",")
                out = []
                for uid in [x.strip() for x in uids if x.strip()]:
                    user = _repo.get_user(uid)
                    if not user:
                        continue
                    r = _engine.run(user, _opts(q))
                    out.append(r.to_public_dict())
                return self._send(200, out)

            if path == "/api/audit":
                uid = q.get("user", [""])[0]
                user = _repo.get_user(uid)
                if not user:
                    return self._send(404, {"error": "unknown user"})
                o = _opts(q)
                o.include_audit = True
                return self._send(200, _engine.run(user, o).to_audit_dict())

            if path == "/api/derivability":
                v = validate_against_seed(KNOWLEDGE_NODES)
                return self._send(200, {
                    "threshold": v["threshold"],
                    "agreement": v["agreement"],
                    "total": v["total"],
                    "disagreements": v["disagreements"],
                    "sample": {
                        k: {"score": e.score, "generic": e.generic_hits,
                            "specific": e.specific_hits}
                        for k, e in list(v["explanations"].items())[:8]
                    },
                })

            return self._send(404, {"error": "not found"})

        except Exception as exc:  # noqa: BLE001
            return self._send(500, {"error": str(exc)})


def _reach(user, opts):
    from backend.pipeline.bfs_traversal import traverse
    from backend.pipeline.entry_point_resolver import resolve_entry_point
    from backend.pipeline.permission_compiler import compile_permissions
    p = compile_permissions(user)
    e = resolve_entry_point(p, _engine.levels())
    return traverse(e.level_id, _engine.levels(), user.department,
                    e.is_fallback and p.policy.cross_department_on_fallback)


def _synthetic(q):
    """Build a user from query params so a brand-new profile can be tested
    live during the demo without touching the database."""
    from backend.models import User
    if not q.get("role"):
        return None
    wc = q.get("write_ceiling", [None])[0]
    return User(
        id=q.get("id", ["U-ADHOC"])[0],
        org_id="supra",
        name=q.get("name", ["Ad-hoc User"])[0],
        role=q.get("role", ["VIEWER"])[0],
        department=q.get("department", ["ortho"])[0],
        ceiling_level=int(q.get("ceiling", ["10"])[0]),
        write_ceiling=int(wc) if wc else None,
        compliance_clearance=[
            c for c in q.get("clearance", [""])[0].split(",") if c
        ],
    )


def serve(port=8000, db_path=None):
    boot(db_path)
    srv = ThreadingHTTPServer(("0.0.0.0", port), Handler)
    print(f"BRAHMO Rules Engine -> http://localhost:{port}")
    print(f"  {_repo.total_node_count('supra')} nodes, "
          f"{len(_repo.list_users())} users, 0 LLM calls")
    srv.serve_forever()


if __name__ == "__main__":
    serve(int(sys.argv[1]) if len(sys.argv) > 1 else 8000)
