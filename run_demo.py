#!/usr/bin/env python3
"""
One command to start the demo.

    python3 run_demo.py            # http://localhost:8000
    python3 run_demo.py 8080

Seeds a fresh SQLite database, verifies the graph is acyclic, prints the
per-user summary, then serves the API and dashboard. No pip install, no
network, no credentials.
"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from backend.pipeline.bfs_traversal import detect_cycles
from backend.pipeline.engine import EngineOptions, RulesEngine
from backend.repository.sqlite_repo import SQLiteRepository
from backend import server


def main():
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8000

    repo, engine = server.boot()
    cycles = detect_cycles(engine.levels())

    print("=" * 68)
    print("BRAHMO Rules Engine — BFS traversal + 5-check filter")
    print("=" * 68)
    print(f"  {repo.total_node_count('supra'):>3} knowledge nodes")
    print(f"  {len(engine.levels()):>3} hierarchy tiers   "
          f"{'acyclic OK' if not cycles else 'CYCLES: ' + str(cycles)}")
    print(f"  {len(repo.list_users()):>3} user profiles")
    print(f"  {0:>3} LLM calls\n")

    print(f"  {'user':<20}{'entry':<16}{'bfs':>5}{'+z2':>5}{'final':>7}{'ms':>8}")
    print("  " + "-" * 60)
    for u in repo.list_users():
        r = engine.run(u, EngineOptions())
        print(f"  {u.name:<20}{r.entry_point:<16}"
              f"{r.funnel['after_bfs']:>5}{r.funnel['after_zone2']:>5}"
              f"{len(r.candidate_set):>7}{r.timing_ms['total_ms']:>8.2f}")
    print()

    server.serve(port)


if __name__ == "__main__":
    main()
