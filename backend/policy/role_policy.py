"""
Declarative role policy.

EVERYTHING about how a role behaves lives in this table. There is no
`if role == "HOD"` anywhere in the pipeline. Adding a Pharmacist, a Quality
Officer or an External Auditor is a data change here (or a row in the `users`
table), never a code change.

That is the property the "surprise user" test is probing.

Two things are compiled per role:

1. read_rule  - how the ceiling maps to readable hierarchy levels.
2. clearance  - which compliance tags the role may see, and whether that
                clearance is scoped to their own department.
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional

# Compliance tags known to the system. A node tagged with any of these is
# withheld unless the user's effective clearance contains that tag.
KNOWN_COMPLIANCE_TAGS = ("MNPI", "PHI", "CONFIDENTIAL")


@dataclass(frozen=True)
class RolePolicy:
    """How one role reads the graph."""

    role: str

    # "AT_OR_BELOW"  -> can read hierarchy levels numerically >= ceiling
    #                   (i.e. their own tier and everything more granular).
    # "ALL"          -> ceiling does not restrict reads at all.
    read_rule: str = "AT_OR_BELOW"

    # Compliance tags this role is granted implicitly, on top of whatever is
    # stored on the user row.
    implicit_clearance: List[str] = field(default_factory=list)

    # If True, implicit clearance only applies to nodes in the user's own
    # department. A HOD sees their own department's MNPI, not Cardiology's.
    clearance_scoped_to_department: bool = True

    # Zone 2 (global) nodes are published hospital-wide. Their hierarchy
    # position records where they were authored, not who may read them.
    # See docs/architecture.md - "Decision 3".
    zone2_bypasses_ceiling: bool = True

    # If the user's department has no matching node in the hierarchy DAG,
    # should BFS fall back to the org root and expand across all departments?
    cross_department_on_fallback: bool = False


# --------------------------------------------------------------------------
# The policy table.
# --------------------------------------------------------------------------
ROLE_POLICIES: Dict[str, RolePolicy] = {
    "VIEWER": RolePolicy(
        role="VIEWER",
        read_rule="AT_OR_BELOW",
        implicit_clearance=[],
        cross_department_on_fallback=False,
    ),
    "EDITOR": RolePolicy(
        role="EDITOR",
        read_rule="AT_OR_BELOW",
        implicit_clearance=[],
        cross_department_on_fallback=False,
    ),
    "HOD": RolePolicy(
        role="HOD",
        # A head of department reads their whole department, including the
        # tiers above their own ward-level staff.
        read_rule="ALL",
        implicit_clearance=["MNPI"],
        clearance_scoped_to_department=True,
        cross_department_on_fallback=False,
    ),
    "QUALITY": RolePolicy(
        role="QUALITY",
        read_rule="AT_OR_BELOW",
        implicit_clearance=[],          # explicit grant on the user row only
        clearance_scoped_to_department=False,   # QA works across departments
        cross_department_on_fallback=True,
    ),
    "AUDITOR": RolePolicy(
        role="AUDITOR",
        read_rule="AT_OR_BELOW",
        implicit_clearance=["MNPI"],
        clearance_scoped_to_department=False,
        cross_department_on_fallback=True,
    ),
    "ADMIN": RolePolicy(
        role="ADMIN",
        read_rule="ALL",
        implicit_clearance=list(KNOWN_COMPLIANCE_TAGS),
        clearance_scoped_to_department=False,
        cross_department_on_fallback=True,
    ),
}

# Any role not in the table gets this. Deliberately the most restrictive
# option: an unknown role must never accidentally be granted more than a
# plain viewer. Fail closed, not open.
DEFAULT_POLICY = RolePolicy(
    role="UNKNOWN",
    read_rule="AT_OR_BELOW",
    implicit_clearance=[],
    clearance_scoped_to_department=True,
    cross_department_on_fallback=False,
)


def policy_for(role: Optional[str]) -> RolePolicy:
    """Look up a role's policy, failing closed on anything unrecognised."""
    if not role:
        return DEFAULT_POLICY
    return ROLE_POLICIES.get(role.upper(), DEFAULT_POLICY)
