"""
Stage 3 - BFS Traversal.

Walks the hierarchy DAG from the user's entry point and returns the set of
hierarchy levels they can structurally reach, with the distance to each.

Two directions, and the distinction matters:

  UPWARD (always)   - follow parent_ids to the root. This is what "context
                      inheritance" means: a ward nurse inherits her department's
                      protocols, her division's, and the hospital's.

  DOWNWARD (scoped) - a user also sees the tiers BELOW their entry point, but
                      only those belonging to their own department. Priya
                      entering at Ortho Ward must reach the TKR Unit and her
                      own patients; she must never reach Cardiology by walking
                      up to Clinical Division and back down.

  The downward scope is what enforces department isolation structurally,
  before any of the five checks run. Users whose department has no home in the
  DAG (Pharmacist, QA, Admin) fall back to the root, and whether they expand
  across all departments is decided by role policy - never hardcoded.

Correctness properties:
  * visited set  - a multi-parent node (Post-TKR Protocol -> Ortho AND Surgery)
                   is processed exactly once, at its shortest distance.
  * FIFO queue   - guarantees the first time a level is dequeued is via a
                   shortest path, so `distance` is genuinely minimal.
  * cycle safe   - the visited set means an accidental cycle terminates rather
                   than looping forever. `detect_cycles` below is the separate
                   load-time guard.
"""

from collections import deque
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set, Tuple

from backend.models import HierarchyLevel


@dataclass
class TraversalResult:
    entry_level_id: str
    # level_id -> shortest distance from entry
    reachable: Dict[str, int] = field(default_factory=dict)
    # Levels reached by walking down into the user's own department.
    expanded_down: Set[str] = field(default_factory=set)
    nodes_visited: int = 0
    multi_parent_hits: List[str] = field(default_factory=list)
    # Co-parent tiers belonging to another department that we deliberately
    # refused to ascend into. Useful evidence in the demo.
    blocked_foreign_parents: List[str] = field(default_factory=list)


def _index(levels: List[HierarchyLevel]):
    by_id = {l.id: l for l in levels}
    children: Dict[str, List[str]] = {l.id: [] for l in levels}
    for l in levels:
        for p in l.parent_ids:
            if p in children:
                children[p].append(l.id)
    return by_id, children


def traverse(
    entry_level_id: str,
    levels: List[HierarchyLevel],
    user_department: Optional[str],
    cross_department: bool = False,
) -> TraversalResult:
    """Breadth-first walk up the DAG, plus a department-scoped walk down."""
    by_id, children = _index(levels)
    if entry_level_id not in by_id:
        raise ValueError(f"entry point '{entry_level_id}' is not in the hierarchy")

    result = TraversalResult(entry_level_id=entry_level_id)
    visited: Set[str] = set()
    queue: deque = deque([(entry_level_id, 0, "ENTRY")])

    while queue:
        level_id, distance, direction = queue.popleft()

        if level_id in visited:
            # Reached again by a second parent path. The visited set means we
            # do NOT re-expand it, and the distance recorded stays the first
            # (shortest) one. This is the multi-parent guarantee.
            if level_id not in result.multi_parent_hits:
                result.multi_parent_hits.append(level_id)
            continue

        visited.add(level_id)
        result.reachable[level_id] = distance
        result.nodes_visited += 1
        if direction == "DOWN":
            result.expanded_down.add(level_id)

        current = by_id[level_id]

        # ---- upward ---------------------------------------------------
        # Ancestors are inherited, with one containment rule: a multi-parent
        # node must not become a bridge into a co-owning department. The
        # Post-TKR Protocol has parents [Ortho, Surgery]. Priya reaches the
        # protocol itself, but walking further up into Surgery would hand her
        # another department's tier through a shared child. So we ascend into
        # department-less tiers (Division, Hospital) and into our own
        # department, and stop at a foreign one.
        for parent_id in current.parent_ids:
            if parent_id not in by_id:
                continue
            if parent_id in visited:
                if parent_id not in result.multi_parent_hits:
                    result.multi_parent_hits.append(parent_id)
                continue
            parent = by_id[parent_id]
            foreign = (
                parent.department is not None
                and parent.department != user_department
            )
            if foreign and not cross_department:
                if parent_id not in result.blocked_foreign_parents:
                    result.blocked_foreign_parents.append(parent_id)
                continue
            queue.append((parent_id, distance + 1, "UP"))

        # ---- downward: department-scoped -----------------------------
        for child_id in children.get(level_id, []):
            if child_id in visited:
                continue
            child = by_id[child_id]
            if cross_department:
                allowed = True
            else:
                # Only descend into tiers owned by the user's own department.
                # A department-less tier (Clinical Division, Global, Admin
                # Division) is NOT descended into, which is precisely what
                # stops Priya reaching Cardiology via the shared parent.
                allowed = (
                    child.department is not None
                    and child.department == user_department
                )
            if allowed:
                queue.append((child_id, distance + 1, "DOWN"))

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
