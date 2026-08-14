#!/usr/bin/env python3
"""
Verify the Supabase connection and that the supplied dataset loaded.

    python scripts/verify_supabase.py

Reports what is configured, connects through the same repository the
application uses, counts the seeded rows, and runs one real pipeline so the
whole path is exercised end to end. Prints no credentials.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.config import (  # noqa: E402
    DatabaseNotConfigured, get_repository, resolve_db_url, settings,
)

EXPECTED = {"knowledge nodes": 50, "users": 7, "hierarchy tiers": 20}


def mask(dsn: str) -> str:
    """Redact the password from a DSN before printing it.

    The password is never printed. Split on the LAST '@' so a password
    containing an unencoded '@' cannot expose part of itself.
    """
    if "@" not in dsn or "//" not in dsn:
        return "(not set)"
    scheme, rest = dsn.split("//", 1)
    creds, host = rest.rsplit("@", 1)
    user = creds.split(":", 1)[0]
    return f"{scheme}//{user}:***@{host}"


def main() -> int:
    print("=" * 66)
    print("Supabase connection check")
    print("=" * 66)
    dsn = resolve_db_url(settings)
    print(f"  DATABASE_BACKEND   {settings.backend}")
    print(f"  SUPABASE_URL       {settings.supabase_url or '(not set)'}")
    print(f"  anon key           {'set' if settings.supabase_anon_key else '(not set)'}"
          "   (not used to read data - see README)")
    print(f"  connection string  {mask(dsn)}")
    if "REPLACE_WITH_YOUR_DB_PASSWORD" in dsn:
        print("\n  SUPABASE_DB_URL still contains the placeholder password.")
        print("  Edit .env and substitute your database password.")
        return 1
    if "pooler.supabase.com" in dsn:
        print("  connection type    Session Pooler (IPv4-proxied)")
    elif dsn.startswith("postgresql://") and ".supabase.co" in dsn:
        print("  connection type    direct (IPv6-only on current projects;")
        print("                     use the Session Pooler URI on IPv4)")
    print()

    if settings.backend != "supabase":
        print(f"  DATABASE_BACKEND is '{settings.backend}', not 'supabase'.")
        print("  Set DATABASE_BACKEND=supabase in .env to test the real path.")
        return 1

    try:
        import psycopg  # noqa: F401
    except ImportError:
        print('  psycopg is not installed.  pip install "psycopg[binary]"')
        return 1

    try:
        repo = get_repository("supabase")
    except DatabaseNotConfigured as exc:
        print("  NOT CONFIGURED\n")
        print(exc)
        return 1
    except Exception as exc:  # connection refused, bad password, DNS, ...
        print(f"  CONNECTION FAILED: {type(exc).__name__}")
        print(f"  {exc}")
        print("\n  'failed to resolve host' usually means the DIRECT host was")
        print("  used on an IPv4 network. Use the Session Pooler URI from")
        print("  Project Settings -> Database -> Connection string.")
        print("  'password authentication failed' with a correct password")
        print("  usually means an unencoded @ : / or # in the URI.")
        return 1

    print("  Connected.\n")

    counts = {
        "knowledge nodes": repo.total_node_count(settings.org_id),
        "users": len(repo.list_users()),
        "hierarchy tiers": len(repo.list_hierarchy(settings.org_id)),
    }
    failures = 0
    for label, expected in EXPECTED.items():
        got = counts[label]
        mark = "ok " if got == expected else "MISMATCH"
        if got != expected:
            failures += 1
        print(f"  {mark:>8}  {label:<18} {got:>3} (expected {expected})")

    if failures:
        print("\n  Row counts are wrong. Re-run supabase/seed.sql in the")
        print("  SQL Editor, after supabase/schema.sql.")
        return 1

    from backend.pipeline.engine import EngineOptions, RulesEngine

    engine = RulesEngine(repo, org_id=settings.org_id)
    print("\n  Pipeline against Supabase:")
    print(f"    {'user':<20}{'entry':<16}{'bfs':>5}{'final':>7}{'ms':>9}")
    print("    " + "-" * 56)
    for user in repo.list_users():
        r = engine.run(user, EngineOptions())
        print(f"    {user.name:<20}{r.entry_point:<16}"
              f"{r.funnel['after_bfs']:>5}{len(r.candidate_set):>7}"
              f"{r.timing_ms['total_ms']:>9.2f}")

    print("\n  Supabase verified.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
