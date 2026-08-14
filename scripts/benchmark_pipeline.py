#!/usr/bin/env python3
"""
Measure the pipeline against whichever database is configured.

    python scripts/benchmark_pipeline.py            # DATABASE_BACKEND from .env
    python scripts/benchmark_pipeline.py --runs 8
    DATABASE_BACKEND=sqlite python scripts/benchmark_pipeline.py

Runs every seeded user several times. The first run per user is reported
separately because it carries connection and plan-cache warm-up; the median of
the rest is the figure that matters. Counts a real round trip per run so the
network cost is visible rather than inferred.
"""

import argparse
import os
import statistics
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.config import DatabaseNotConfigured, get_repository, settings
from backend.pipeline.engine import EngineOptions, RulesEngine

BUDGET_MS = 500


class CountingCursor:
    """Wraps the connection to count statements actually sent."""

    def __init__(self, repo):
        self.n = 0
        self.repo = repo
        self._patch()

    def _patch(self):
        repo = self.repo
        if hasattr(repo, "_conn") and hasattr(repo._conn, "execute"):
            inner, counter = repo._conn, self

            class Spy:
                def execute(self, sql, params=()):
                    counter.n += 1
                    return inner.execute(sql, params)

                def __getattr__(self, name):
                    return getattr(inner, name)

            repo._conn = Spy()
        elif hasattr(repo, "_rows"):
            inner, counter = repo._rows, self

            def spy(sql, params=None):
                counter.n += 1
                return inner(sql, params)

            repo._rows = spy


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", type=int, default=5)
    args = ap.parse_args()

    try:
        repo = get_repository()
    except DatabaseNotConfigured as exc:
        print(exc)
        return 1

    engine = RulesEngine(repo, org_id=settings.org_id)
    engine.levels()  # hierarchy is loaded once per session, as in production

    backend = getattr(repo, "backend_name", "unknown")
    print("=" * 78)
    print(f"Pipeline benchmark - backend={backend}  runs={args.runs}  "
          f"budget={BUDGET_MS}ms")
    print("=" * 78)
    print(f"  {'user':<20}{'bfs':>5}{'+z2':>5}{'final':>7}"
          f"{'first':>10}{'median':>10}{'queries':>9}")
    print("  " + "-" * 74)

    slowest = 0.0
    for user in repo.list_users():
        times, result = [], None
        counter = CountingCursor(repo)
        for i in range(args.runs):
            before = counter.n
            t = time.perf_counter()
            result = engine.run(user, EngineOptions())
            times.append((time.perf_counter() - t) * 1000)
            if i == 0:
                per_run = counter.n - before
        median = statistics.median(times[1:]) if len(times) > 1 else times[0]
        slowest = max(slowest, median)
        print(f"  {user.name:<20}{result.funnel['after_bfs']:>5}"
              f"{result.funnel['after_zone2']:>5}"
              f"{len(result.candidate_set):>7}"
              f"{times[0]:>9.1f}ms{median:>9.1f}ms{per_run:>9}")

    print()
    if slowest < BUDGET_MS:
        print(f"  Slowest median {slowest:.1f}ms - within the {BUDGET_MS}ms budget.")
        return 0
    print(f"  Slowest median {slowest:.1f}ms - OVER the {BUDGET_MS}ms budget.")
    print("  Each remaining query is one network round trip; check the")
    print("  'queries' column and your latency to the database region.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
