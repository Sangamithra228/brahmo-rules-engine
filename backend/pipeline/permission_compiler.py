"""
Stage 1 - Permission Compiler.

Runs ONCE per session. Turns a user row into:

  * level_map : {level_number: {"can_read": bool, "can_write": bool}}
                a plain dict -> every later permission test is one O(1)
                hash lookup, not a database round trip.
  * clearance : the set of compliance tags this user may see.

Why this matters: after BFS + Zone 2 injection there are N nodes to test. If
each test hit the database that is the N+1 query problem - 500 round trips for
one session. Compiling once turns the whole permission check into N dict
lookups, which is microseconds.

The compiled object is immutable and cacheable. In production it would be
built at session start and held for the life of the session.
"""

from dataclasses import dataclass
from typing import Dict, List, Optional, Set

from backend.models import User
from backend.policy.role_policy import KNOWN_COMPLIANCE_TAGS, RolePolicy, policy_for

# The DAG spans levels 1..15 (schema CHECK constraint).
MIN_LEVEL = 1
MAX_LEVEL = 15


@dataclass(frozen=True)
class CompiledPermissions:
    user_id: str
    role: str
    department: str
    ceiling_level: int
    write_ceiling: Optional[int]
    policy: RolePolicy
    level_map: Dict[int, Dict[str, bool]]
    clearance: Set[str]

    # ---- O(1) accessors ------------------------------------------------
    def can_read_level(self, level: int) -> bool:
        entry = self.level_map.get(level)
        return bool(entry and entry["can_read"])

    def can_write_level(self, level: int) -> bool:
        entry = self.level_map.get(level)
        return bool(entry and entry["can_write"])

    def clears_tags(self, tags: List[str], node_department: Optional[str]) -> bool:
        """True if the user may see a node carrying `tags`.

        An untagged node is visible to everyone. A tagged node needs EVERY tag
        to be cleared - CONFIDENTIAL+MNPI needs both, not either.
        """
        if not tags:
            return True

        # Scoped clearance: a HOD's MNPI clearance covers their own department
        # only. Nodes belonging to another department (or to no department,
        # i.e. hospital-wide board material) are not covered.
        if self.policy.clearance_scoped_to_department:
            if node_department is None or node_department != self.department:
                # Fall back to explicitly granted tags on the user row, which
                # are never department-scoped.
                return all(t in self.explicit_clearance for t in tags)

        return all(t in self.clearance for t in tags)

    # Populated at construction; kept separate so scoped logic can consult it.
    @property
    def explicit_clearance(self) -> Set[str]:
        return self._explicit  # type: ignore[attr-defined]


def compile_permissions(user: User) -> CompiledPermissions:
    """Build the O(1) permission structure for one user."""
    policy = policy_for(user.role)

    # --- level map ------------------------------------------------------
    level_map: Dict[int, Dict[str, bool]] = {}
    for level in range(MIN_LEVEL, MAX_LEVEL + 1):
        if policy.read_rule == "ALL":
            can_read = True
        else:
            # "AT_OR_BELOW": a bigger level number is a more granular tier.
            # Ceiling 10 -> ward (10) and patient (12) readable; department
            # (5) and division (3) are above the ceiling and are not.
            can_read = level >= user.ceiling_level

        if user.write_ceiling is None:
            can_write = False
        else:
            can_write = level >= user.write_ceiling

        level_map[level] = {"can_read": can_read, "can_write": can_write}

    # --- clearance ------------------------------------------------------
    explicit = {t for t in (user.compliance_clearance or []) if t}
    clearance = set(explicit) | set(policy.implicit_clearance)
    # Never grant a tag the system does not know about.
    clearance &= set(KNOWN_COMPLIANCE_TAGS)

    compiled = CompiledPermissions(
        user_id=user.id,
        role=user.role,
        department=user.department,
        ceiling_level=user.ceiling_level,
        write_ceiling=user.write_ceiling,
        policy=policy,
        level_map=level_map,
        clearance=clearance,
    )
    # frozen dataclass -> bypass __setattr__ once, at construction only.
    object.__setattr__(compiled, "_explicit", explicit)
    return compiled
