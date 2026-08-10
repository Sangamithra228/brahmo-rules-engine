"""
Stage 2 - Entry Point Resolver.

Maps a user to the DAG node they start their traversal from.

Rule (derived from the worked examples in the assessment):

  Among hierarchy nodes whose department matches the user's department, pick
  the SHALLOWEST tier that is still at or below the user's ceiling - i.e. the
  smallest level_number >= ceiling_level.

Checks against the spec's stated entry points:

  Priya   ceiling 10, ortho    -> ortho levels >=10 are {10, 12} -> HL-10-ORTHO-W  (L10)
  Vikram  ceiling  4, ortho    -> ortho levels >= 4 are {5,8,8,8,10,12} -> HL-05-ORTHO (L5)
  Ananya  ceiling  8, medicine -> medicine >= 8 are {8,10}   -> HL-08-MED-GEN (L8)
  Sharma  ceiling  4, medicine -> medicine >= 4 are {5,8,10} -> HL-05-MED (L5)

Fallbacks, in order:
  1. No department node at or below the ceiling -> take the deepest node that
     department does have.
  2. Department has no node in the DAG at all (Pharmacist, QA, Admin) -> enter
     at the org root. Whether that user then expands across departments is a
     role-policy decision, not a hardcoded one.
"""

from dataclasses import dataclass
from typing import Dict, List, Optional

from backend.models import HierarchyLevel
from backend.pipeline.permission_compiler import CompiledPermissions


@dataclass(frozen=True)
class EntryPoint:
    level_id: str
    level_name: str
    level_number: int
    department: Optional[str]
    # True when the user's department had no home in the DAG and we fell back
    # to the root. Drives cross-department expansion via role policy.
    is_fallback: bool
    reason: str


def _root_of(levels: List[HierarchyLevel]) -> HierarchyLevel:
    """The DAG root is the node with no parents. Lowest level_number wins ties."""
    roots = [l for l in levels if not l.parent_ids]
    if not roots:
        # Degenerate graph - fall back to the shallowest node rather than crash.
        return min(levels, key=lambda l: l.level_number)
    return min(roots, key=lambda l: l.level_number)


def resolve_entry_point(
    perms: CompiledPermissions,
    levels: List[HierarchyLevel],
) -> EntryPoint:
    if not levels:
        raise ValueError("hierarchy is empty - cannot resolve an entry point")

    dept = perms.department
    dept_levels = [l for l in levels if l.department == dept]

    if dept_levels:
        at_or_below = [l for l in dept_levels if l.level_number >= perms.ceiling_level]
        if at_or_below:
            chosen = min(at_or_below, key=lambda l: (l.level_number, l.id))
            reason = (
                f"shallowest '{dept}' tier at or below ceiling L{perms.ceiling_level}"
            )
        else:
            chosen = max(dept_levels, key=lambda l: (l.level_number, l.id))
            reason = (
                f"no '{dept}' tier at or below ceiling L{perms.ceiling_level}; "
                f"used deepest available"
            )
        return EntryPoint(
            level_id=chosen.id,
            level_name=chosen.level_name,
            level_number=chosen.level_number,
            department=chosen.department,
            is_fallback=False,
            reason=reason,
        )

    root = _root_of(levels)
    return EntryPoint(
        level_id=root.id,
        level_name=root.level_name,
        level_number=root.level_number,
        department=root.department,
        is_fallback=True,
        reason=(
            f"department '{dept}' has no node in the DAG; entered at org root "
            f"'{root.id}'"
        ),
    )
