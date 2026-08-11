"""
Stage 4 - Zone 2 Injection.

Zone 2 nodes are hospital-wide constraints that must be present in EVERY
session regardless of where the user sits in the graph. Priya's BFS only walks
the Ortho branch; without injection she would never see "never combine
Warfarin with NSAIDs", which is exactly the class of knowledge that gets
people killed.

Position in the pipeline is load-bearing: injection happens AFTER BFS and
BEFORE the five checks. Injected nodes are candidates, not grants - a Zone 2
node that is MNPI-tagged, superseded or purely derivable is still removed
downstream. Injection widens the input to the sieve; it does not punch a hole
through it.

Zone is a property of the NODE, not of its hierarchy level. HL-GLOBAL also
hosts a zone-1 node (N-D03, "Normal Vital Sign Ranges"), which is general
medical knowledge and must not ride along on the injection.
"""

from dataclasses import dataclass, field
from typing import Dict, List

# Zone 2 nodes have no traversal path, so `distance_from_entry` is not a walk
# length. They are annotated at this constant, which sorts them below anything
# actually on the user's path and maps to CONSTRAINT_ONLY compression - the
# right hint for a short global rule.
ZONE2_DISTANCE = 4


@dataclass
class InjectionResult:
    level_ids: List[str]
    injected_node_ids: List[str] = field(default_factory=list)
    distances: Dict[str, int] = field(default_factory=dict)
    enabled: bool = True


def inject(
    reachable: Dict[str, int],
    zone2_node_ids: List[str],
    enabled: bool = True,
) -> InjectionResult:
    return InjectionResult(
        level_ids=list(reachable.keys()),
        injected_node_ids=list(zone2_node_ids) if enabled else [],
        distances=dict(reachable),
        enabled=enabled,
    )
