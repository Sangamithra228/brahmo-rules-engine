#!/usr/bin/env python3
"""
Start the backend and print a per-user summary.

    python run_demo.py                 # port 8000, DATABASE_BACKEND from .env
    python run_demo.py 8080

Database selection follows DATABASE_BACKEND (default: supabase). To run
offline against the local SQLite fallback:

    DATABASE_BACKEND=sqlite python run_demo.py
    # PowerShell:  $env:DATABASE_BACKEND="sqlite"; python run_demo.py

This serves the API. For the React dashboard run `npm run dev` in frontend/,
or `npm run build` once and this will serve the built files.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from backend import server
from backend.config import DatabaseNotConfigured, settings
from backend.pipeline.bfs_traversal import detect_cycles
from backend.pipeline.engine import EngineOptions


def main():
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8000

    try:
        repo, engine = server.boot()
    except DatabaseNotConfigured as exc:
        print("\n" + "=" * 70)
        print("Cannot start: database not configured")
        print("=" * 70)
        print(exc)
        sys.exit(1)

    cycles = detect_cycles(engine.levels())

    print("=" * 70)
    print("BRAHMO Rules Engine - BFS traversal + 5-check filter")
    print("=" * 70)
    print(f"  database        {repo.backend_name}")
    print(f"  knowledge nodes {repo.total_node_count(settings.org_id)}")
    print(f"  hierarchy tiers {len(engine.levels())}  "
          f"{'acyclic OK' if not cycles else 'CYCLES: ' + str(cycles)}")
    print(f"  user profiles   {len(repo.list_users())}")
    print(f"  LLM calls       0\n")

    print(f"  {'user':<20}{'entry':<16}{'bfs':>5}{'+z2':>5}{'final':>7}{'ms':>8}")
    print("  " + "-" * 61)
    for u in repo.list_users():
        r = engine.run(u, EngineOptions())
        print(f"  {u.name:<20}{r.entry_point:<16}"
              f"{r.funnel['after_bfs']:>5}{r.funnel['after_zone2']:>5}"
              f"{len(r.candidate_set):>7}{r.timing_ms['total_ms']:>8.2f}")
    print()

    server.serve(port)


if __name__ == "__main__":
    main()
