"""
Zero-dependency HTTP API (Python standard library only).

`backend/main.py` is the primary FastAPI application. This mirror exists so
the pipeline can be exercised and demonstrated without pip install - useful
offline and as a fallback if the Python environment misbehaves before a demo.

Both call backend/api.py, so behaviour cannot drift between them.

Routes match FastAPI:
  GET  /health
  GET  /users
  GET  /users/{id}
  GET  /hierarchy
  GET|POST /pipeline/run
  GET  /pipeline/compare
  GET  /pipeline/{run_id}
  GET  /admin/audit
  GET  /admin/derivability
"""

import json
import logging
import os
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend import api
from backend.config import get_repository, settings
from backend.pipeline.engine import RulesEngine

log = logging.getLogger("brahmo")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DIST = os.path.join(ROOT, "frontend", "dist")

_repo = None
_engine = None


def boot(backend=None):
    global _repo, _engine
    _repo = get_repository(backend)
    _engine = RulesEngine(_repo, org_id=settings.org_id)
    return _repo, _engine


def _flat(qs):
    """parse_qs gives lists; the API layer wants scalars."""
    return {k: (v[0] if len(v) == 1 else v) for k, v in qs.items()}


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
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
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Allow-Methods", "GET,POST,OPTIONS")
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def do_OPTIONS(self):
        self._send(204, b"", "text/plain")

    def do_POST(self):
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b"{}"
        try:
            params = json.loads(raw or b"{}")
        except json.JSONDecodeError:
            return self._send(400, {"detail": "body must be JSON"})
        self._route(urlparse(self.path).path, params)

    def do_GET(self):
        u = urlparse(self.path)
        self._route(u.path, _flat(parse_qs(u.query)))

    def _route(self, path, params):
        try:
            if path in ("/", "/index.html"):
                return self._serve_index()

            if path == "/health":
                return self._send(200, api.health(_repo, _engine))
            if path == "/users":
                return self._send(200, api.list_users(_repo))
            if path.startswith("/users/"):
                return self._send(200, api.get_user(_repo, path.split("/")[2]))
            if path == "/hierarchy":
                return self._send(200, api.hierarchy(_engine))

            if path == "/pipeline/run":
                return self._send(200, api.run_pipeline(_repo, _engine, params))
            if path == "/pipeline/compare":
                ids = params.get("users") or "U-PRIYA,U-VIKRAM,U-SURESH"
                return self._send(200, api.compare(
                    _repo, _engine,
                    [x.strip() for x in ids.split(",") if x.strip()], params))
            if path.startswith("/pipeline/"):
                return self._send(200, api.get_run(path.split("/")[2]))

            if path == "/admin/audit":
                return self._send(200, api.audit(_repo, _engine, params))
            if path == "/admin/derivability":
                return self._send(200, api.derivability_report())

            if path.startswith("/assets/"):
                return self._serve_asset(path)

            return self._send(404, {"detail": "not found"})

        except api.ApiError as exc:
            # Deliberate, caller-safe messages only.
            return self._send(exc.status, {"detail": exc.message})
        except Exception:  # noqa: BLE001
            # Never return the exception text: it can carry SQL fragments,
            # file paths, or the content of rows the caller may not see.
            log.exception("unhandled error on %s", path)
            return self._send(500, {"detail": "Internal server error"})

    def _serve_index(self):
        built = os.path.join(DIST, "index.html")
        if os.path.exists(built):
            with open(built, "rb") as f:
                return self._send(200, f.read(), "text/html; charset=utf-8")
        return self._send(200, (
            b"<!doctype html><meta charset=utf-8>"
            b"<title>BRAHMO Rules Engine</title>"
            b"<body style='font-family:system-ui;max-width:44rem;margin:4rem auto;"
            b"line-height:1.6;color:#0D1B1A'>"
            b"<h1 style='font-size:1.1rem;letter-spacing:.12em;text-transform:uppercase'>"
            b"BRAHMO Rules Engine</h1>"
            b"<p>The API is running. The React dashboard has not been built yet.</p>"
            b"<pre style='background:#F4F7F6;padding:1rem;border-radius:4px'>"
            b"cd frontend\nnpm install\nnpm run dev     # http://localhost:5173\n"
            b"\n# or build once and serve from here:\nnpm run build</pre>"
            b"<p>API: <a href='/health'>/health</a> &middot; "
            b"<a href='/users'>/users</a> &middot; "
            b"<a href='/pipeline/run?user=U-PRIYA'>/pipeline/run?user=U-PRIYA</a></p>"
            b"</body>"), "text/html; charset=utf-8")

    def _serve_asset(self, path):
        safe = os.path.normpath(path.lstrip("/")).replace("..", "")
        full = os.path.join(DIST, safe)
        if not os.path.isfile(full):
            return self._send(404, {"detail": "not found"})
        ctype = ("text/css" if full.endswith(".css")
                 else "application/javascript" if full.endswith(".js")
                 else "application/octet-stream")
        with open(full, "rb") as f:
            return self._send(200, f.read(), ctype)


def serve(port=8000, backend=None):
    boot(backend)
    srv = ThreadingHTTPServer(("0.0.0.0", port), Handler)
    print(f"BRAHMO Rules Engine -> http://localhost:{port}")
    print(f"  backend={settings.backend}  "
          f"{_repo.total_node_count(settings.org_id)} nodes  "
          f"{len(_repo.list_users())} users  0 LLM calls")
    srv.serve_forever()


if __name__ == "__main__":
    serve(int(sys.argv[1]) if len(sys.argv) > 1 else 8000)
