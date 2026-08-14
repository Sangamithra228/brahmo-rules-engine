"""
Stage 6 - Candidate Set Assembler.

Annotates surviving nodes for the downstream Composition Agent. This is the
interface contract; the Composition Agent is out of scope for this assessment.

`compression_hint` is derived from traversal distance, on the reasoning that
proximity tracks specificity: a node on the user's own ward is about her
patients and should be passed through whole, while a hospital-wide rule four
hops up only needs its constraint carried.

  distance 0-1 -> FULL             (own ward / own patients)
  distance 2   -> COMPRESSED       (department / sub-department)
  distance 3+  -> CONSTRAINT_ONLY  (division, hospital, global)

One override: a CONSTRAINT is never compressed below CONSTRAINT_ONLY, and a
node with importance >= 0.95 is never reduced past COMPRESSED regardless of
distance. Losing the wording of a life-safety rule to save tokens is a bad
trade, and this is the sort of judgement the hint exists to encode.
"""

from typing import Dict, List

from backend.models import CandidateNode, KnowledgeNode
from backend.pipeline.zone2_injector import ZONE2_DISTANCE

CRITICAL_IMPORTANCE = 0.95


def _hint(distance: int, importance: float) -> str:
    if distance <= 1:
        base = "FULL"
    elif distance == 2:
        base = "COMPRESSED"
    else:
        base = "CONSTRAINT_ONLY"

    if importance >= CRITICAL_IMPORTANCE and base == "CONSTRAINT_ONLY":
        return "COMPRESSED"
    return base


def assemble(
    nodes: List[KnowledgeNode],
    distances: Dict[str, int],
) -> List[CandidateNode]:
    out: List[CandidateNode] = []

    for n in nodes:
        # Zone 2 is a property of the node. A global node that also sits on
        # the user's ancestor path was reached by BFS, so it is not "injected".
        is_zone2 = n.zone == 2 and n.hierarchy_level_id not in distances
        distance = (
            ZONE2_DISTANCE if is_zone2
            else distances.get(n.hierarchy_level_id, ZONE2_DISTANCE)
        )
        out.append(
            CandidateNode(
                id=n.id,
                type=n.type,
                title=n.title,
                content=n.content,
                importance=round(float(n.importance), 2),
                zone=n.zone,
                hierarchy_level=n.hierarchy_level,
                department=n.department,
                distance_from_entry=distance,
                compression_hint=_hint(distance, float(n.importance)),
                source="ZONE2" if is_zone2 else "BFS",
            )
        )

    # Deterministic ordering: importance desc, then id. Same input -> same
    # bytes out, every run. There is a test asserting the output hash.
    out.sort(key=lambda c: (-c.importance, c.id))
    return out
