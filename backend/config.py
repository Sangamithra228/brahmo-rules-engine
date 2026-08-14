"""
Application configuration and the database factory.

Supabase / PostgreSQL is the PRIMARY backend. SQLite exists only as an
explicit local fallback for offline development and the test suite.

The default is deliberately NOT silent: if DATABASE_BACKEND is unset the app
selects Supabase, and if Supabase is not configured it fails with an
actionable message rather than quietly dropping to SQLite. A demo that
silently ran against the wrong database would be worse than one that refuses
to start.

    DATABASE_BACKEND=supabase   (default)
    DATABASE_BACKEND=sqlite     (explicit opt-in to the local fallback)
"""

import os

DEFAULT_BACKEND = "supabase"


def _load_dotenv() -> None:
    """Minimal .env loader so the app does not depend on python-dotenv."""
    path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"
    )
    if not os.path.exists(path):
        return
    with open(path) as fh:
        for line in fh:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            os.environ.setdefault(key.strip(), value.strip().strip("'\""))


_load_dotenv()


class Settings:
    backend = os.environ.get("DATABASE_BACKEND", DEFAULT_BACKEND).lower().strip()
    org_id = os.environ.get("BRAHMO_ORG_ID", "supra")
    derivability_threshold = float(
        os.environ.get("BRAHMO_DERIVABILITY_THRESHOLD", "0.7")
    )
    permission_mode = os.environ.get("BRAHMO_PERMISSION_MODE", "strict")
    # Supabase project identity. SUPABASE_URL / SUPABASE_ANON_KEY describe the
    # PostgREST endpoint; this backend does NOT use them to read data - see
    # the note in SUPABASE_SETUP_HELP - but they are read here so the project
    # reference can be derived and reported.
    supabase_url = os.environ.get("SUPABASE_URL", "").rstrip("/")
    supabase_anon_key = os.environ.get("SUPABASE_ANON_KEY", "")
    # The complete PostgreSQL DSN, including credentials. This is the only
    # source of connection details; nothing is derived from SUPABASE_URL.
    supabase_db_url = os.environ.get("SUPABASE_DB_URL", "")
    sqlite_path = os.environ.get("SQLITE_PATH") or None

    # The /admin routes expose the exclusion trail - the ids and titles of
    # nodes a user was NOT given. That is precisely what silent exclusion
    # hides, so the routes cannot be open. Default posture: loopback only,
    # which keeps the local demo working with no configuration. Set
    # BRAHMO_ADMIN_TOKEN to require a header instead, which is what any
    # non-local deployment must do.
    admin_token = os.environ.get("BRAHMO_ADMIN_TOKEN", "")
    cors_origins = [
        o.strip() for o in os.environ.get(
            "BRAHMO_CORS_ORIGINS",
            "http://localhost:5173,http://127.0.0.1:5173,"
            "http://localhost:8000,http://127.0.0.1:8000",
        ).split(",") if o.strip()
    ]


def project_ref(url: str) -> str:
    """https://abc123.supabase.co -> abc123"""
    if not url:
        return ""
    host = url.split("//")[-1].split("/")[0]
    return host.split(".")[0]


def resolve_db_url(cfg) -> str:
    """The connection string psycopg needs: taken verbatim from
    SUPABASE_DB_URL.

    The host is NOT constructed from SUPABASE_URL. Building
    db.<ref>.supabase.co assumes the direct connection, which is IPv6-only on
    current Supabase projects and fails to resolve on IPv4 networks. Supplying
    the whole DSN lets the Session Pooler host (IPv4-proxied) be used without
    the application knowing anything about Supabase's hostname scheme.
    """
    return cfg.supabase_db_url


settings = Settings()


SUPABASE_SETUP_HELP = """
Supabase is the primary database and is not fully configured.

This backend reads the graph over a direct PostgreSQL connection (psycopg),
because the five checks execute as progressive SQL WHERE clauses inside the
database. A publishable / anon key addresses the PostgREST API and cannot
drive those predicates, so SUPABASE_URL and SUPABASE_ANON_KEY alone are not
enough: a database credential is required.

  1. SQL Editor -> run, in order:
       supabase/schema.sql
       supabase/seed.sql
       supabase/rls_policies.sql   (optional, defence in depth)
  2. cp .env.example .env   (Windows: copy .env.example .env)
  3. Set SUPABASE_DB_URL to the complete connection string from
       Project Settings -> Database -> Connection string -> URI

     On an IPv4 network use the SESSION POOLER string, which Supabase
     proxies over IPv4. It looks like:

       postgresql://postgres.<project-ref>:<password>
         @aws-0-<region>.pooler.supabase.com:5432/postgres

     The direct db.<ref>.supabase.co host is IPv6-only on current projects
     and will fail to resolve on an IPv4-only network.

     If the password contains @ : / or #, percent-encode it in the URI
     (@ -> %40, : -> %3A, / -> %2F, # -> %23).
  4. pip install "psycopg[binary]"
  5. Verify:  python scripts/verify_supabase.py

To run offline against the local SQLite fallback instead:

  DATABASE_BACKEND=sqlite python run_demo.py

  PowerShell:  $env:DATABASE_BACKEND="sqlite"; python run_demo.py
"""


class DatabaseNotConfigured(RuntimeError):
    pass


def get_repository(backend: str = None, auto_seed_sqlite: bool = True):
    """Return the repository for the configured backend.

    Raises DatabaseNotConfigured with setup instructions rather than falling
    back silently.
    """
    backend = (backend or settings.backend).lower().strip()

    if backend == "sqlite":
        from backend.repository.sqlite_repo import SQLiteRepository

        repo = SQLiteRepository(settings.sqlite_path)
        if auto_seed_sqlite and not repo.is_seeded(settings.org_id):
            repo.initialise()
            repo.seed()
        return repo

    if backend == "supabase":
        dsn = resolve_db_url(settings)
        if not dsn:
            raise DatabaseNotConfigured(
                "SUPABASE_DB_URL is not set." + SUPABASE_SETUP_HELP
            )
        try:
            import psycopg  # noqa: F401
        except ImportError as exc:
            raise DatabaseNotConfigured(
                "The psycopg driver is not installed "
                '(pip install "psycopg[binary]").' + SUPABASE_SETUP_HELP
            ) from exc

        from backend.repository.supabase_repo import SupabaseRepository

        return SupabaseRepository(dsn)

    raise DatabaseNotConfigured(
        f"DATABASE_BACKEND='{backend}' is not recognised. "
        "Use 'supabase' (default) or 'sqlite'."
    )
