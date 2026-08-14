"""
Stage 3 - BFS Traversal.

Walks UP the hierarchy DAG from the user's entry point, following parent_ids,
and records the shortest distance to every ancestor reached.

    entry_point -> parent -> parent -> ... -> root

That is the whole of it. There is no downward walk: a user inherits the
context of the tiers above them, not the tiers beneath them. Department
isolation therefore falls out of the DAG's shape rather than from any rule in
this module - Cardiology is never an ancestor of the Ortho Ward, so Priya
cannot reach it.

Correctness properties:
  * FIFO queue    - the first time a tier is dequeued is via a shortest path,
                    so `distance` is genuinely minimal.
  * visited set   - a multi-parent tier (Post-TKR Protocol -> Ortho AND
                    Surgery) is enqueued from both paths but processed once.
  * cycle safe    - the visited set means an accidental cycle terminates
                    rather than looping forever. `detect_cycles` below is the
                    separate load-time guard.

The traversal reads hierarchy tiers only. Knowledge-node content is never
fetched here; BFS produces reachable tier ids and distances, and the five
checks then run as SQL over that set.
"""

from collections import deque
from dataclasses import dataclass, field
from typing import Dict, List, Set, Tuple

from backend.models import HierarchyLevel


@dataclass
class TraversalResult:
    entry_level_id: str
    # level_id -> shortest distance from entry
    reachable: Dict[str, int] = field(default_factory=dict)
    nodes_visited: int = 0
    # Tiers re-encountered through a second parent path and skipped by the
    # visited set. Evidence that multi-parent handling is working.
    multi_parent_hits: List[str] = field(default_factory=list)


def _index(levels: List[HierarchyLevel]):
    return {l.id: l for l in levels}


def traverse(
    entry_level_id: str,
    levels: List[HierarchyLevel],
) -> TraversalResult:
    """Breadth-first walk UP the DAG from `entry_level_id`."""
    by_id = _index(levels)
    if entry_level_id not in by_id:
        raise ValueError(f"entry point '{entry_level_id}' is not in the hierarchy")

    result = TraversalResult(entry_level_id=entry_level_id)
    visited: Set[str] = set()
    queue: deque = deque([(entry_level_id, 0)])

    while queue:
        level_id, distance = queue.popleft()

        if level_id in visited:
            # Reached again through a second parent path. The visited set
            # means we do not re-expand it, and the distance recorded stays
            # the first (shortest) one.
            if level_id not in result.multi_parent_hits:
                result.multi_parent_hits.append(level_id)
            continue

        visited.add(level_id)
        result.reachable[level_id] = distance
        result.nodes_visited += 1

        for parent_id in by_id[level_id].parent_ids:
            if parent_id not in by_id:
                continue
            if parent_id in visited:
                if parent_id not in result.multi_parent_hits:
                    result.multi_parent_hits.append(parent_id)
                continue
            queue.append((parent_id, distance + 1))

    return result


# --------------------------------------------------------------------------
# Cycle prevention
# --------------------------------------------------------------------------
def detect_cycles(levels: List[HierarchyLevel]) -> List[List[str]]:
    """Return every cycle found in the parent graph. Empty list == valid DAG.

    The BFS above cannot infinite-loop regardless (visited set), but silently
    tolerating a cycle would mean the graph is lying about being a DAG. This
    runs at load time and on insert so a bad edge is rejected at the door
    rather than discovered at query time.

    Iterative three-colour DFS - no recursion limit to trip over.
    """
    by_id = {l.id: l for l in levels}
    WHITE, GREY, BLACK = 0, 1, 2
    colour: Dict[str, int] = {lid: WHITE for lid in by_id}
    cycles: List[List[str]] = []

    for start in by_id:
        if colour[start] != WHITE:
            continue
        stack: List[Tuple[str, int]] = [(start, 0)]
        path: List[str] = []
        while stack:
            node, child_idx = stack.pop()
            if child_idx == 0:
                if colour[node] == GREY:
                    continue
                colour[node] = GREY
                path.append(node)
            parents = [p for p in by_id[node].parent_ids if p in by_id]
            if child_idx < len(parents):
                stack.append((node, child_idx + 1))
                nxt = parents[child_idx]
                if colour.get(nxt) == GREY:
                    # Found a back edge -> cycle.
                    if nxt in path:
                        cycles.append(path[path.index(nxt):] + [nxt])
                elif colour.get(nxt) == WHITE:
                    stack.append((nxt, 0))
            else:
                colour[node] = BLACK
                if path and path[-1] == node:
                    path.pop()
    return cycles


def would_create_cycle(
    levels: List[HierarchyLevel], child_id: str, new_parent_id: str
) -> bool:
    """Insert-time guard: would adding child -> new_parent close a loop?

    True iff `child_id` is already an ancestor of `new_parent_id`.
    """
    by_id = {l.id: l for l in levels}
    if new_parent_id not in by_id:
        return False
    seen: Set[str] = set()
    queue = deque([new_parent_id])
    while queue:
        cur = queue.popleft()
        if cur == child_id:
            return True
        if cur in seen:
            continue
        seen.add(cur)
        for p in by_id[cur].parent_ids:
            if p in by_id:
                queue.append(p)
    return False
