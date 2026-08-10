"""Domain models for the BRAHMO Rules Engine."""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass(frozen=True)
class HierarchyLevel:
    """A node in the org DAG. `parent_ids` may hold >1 entry (multi-parent)."""

    id: str
    org_id: str
    level_number: int
    level_name: str
    department: Optional[str]
    parent_ids: List[str]
    zone: int


@dataclass(frozen=True)
class User:
    id: str
    org_id: str
    name: str
    role: str
    department: str
    ceiling_level: int
    write_ceiling: Optional[int]
    compliance_clearance: List[str]
    status: str = "ACTIVE"


@dataclass(frozen=True)
class KnowledgeNode:
    id: str
    org_id: str
    hierarchy_level_id: str
    type: str
    title: str
    content: str
    importance: float
    zone: int
    status: str
    derivability_score: float
    compliance_tags: List[str]
    department: Optional[str]
    valid_until: Optional[str] = None
    superseded_by: Optional[str] = None
    # Populated by the repository join so checks never need a second query.
    hierarchy_level: int = 0


@dataclass
class CandidateNode:
    """A node that survived all five checks, annotated for the downstream
    Composition Agent. This is the interface contract."""

    id: str
    type: str
    title: str
    content: str
    importance: float
    zone: int
    hierarchy_level: int
    department: Optional[str]
    distance_from_entry: int
    compression_hint: str
    source: str  # "BFS" or "ZONE2"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "type": self.type,
            "title": self.title,
            "content": self.content,
            "importance": self.importance,
            "zone": self.zone,
            "hierarchy_level": self.hierarchy_level,
            "department": self.department,
            "distance_from_entry": self.distance_from_entry,
            "compression_hint": self.compression_hint,
            "source": self.source,
        }


@dataclass
class ExclusionRecord:
    """Why a node did not survive.

    NOTE: this never appears in the user-facing response. Silent exclusion
    means the caller cannot tell that anything was removed. It is exposed only
    on the separate /api/audit endpoint, which is operator-only.
    """

    node_id: str
    node_title: str
    check: str
    reason: str


@dataclass
class PipelineResult:
    user: User
    entry_point: Optional[str]
    entry_point_name: Optional[str]
    funnel: Dict[str, int] = field(default_factory=dict)
    timing_ms: Dict[str, float] = field(default_factory=dict)
    candidate_set: List[CandidateNode] = field(default_factory=list)
    exclusions: List[ExclusionRecord] = field(default_factory=list)
    notes: List[str] = field(default_factory=list)

    def to_public_dict(self) -> Dict[str, Any]:
        """The response a caller / downstream agent receives.

        Contains NO indication that any node was excluded: no counts of hidden
        nodes, no 403s, no 'restricted' placeholders.
        """
        return {
            "user": self.user.id,
            "user_name": self.user.name,
            "role": self.user.role,
            "department": self.user.department,
            "ceiling_level": self.user.ceiling_level,
            "entry_point": self.entry_point,
            "entry_point_name": self.entry_point_name,
            "pipeline_timing": self.timing_ms,
            "funnel": self.funnel,
            "candidate_set": [c.to_dict() for c in self.candidate_set],
        }

    def to_audit_dict(self) -> Dict[str, Any]:
        """Operator-only view. Explains every exclusion."""
        return {
            "user": self.user.id,
            "notes": self.notes,
            "exclusions": [
                {
                    "node_id": e.node_id,
                    "node_title": e.node_title,
                    "check": e.check,
                    "reason": e.reason,
                }
                for e in self.exclusions
            ],
        }
