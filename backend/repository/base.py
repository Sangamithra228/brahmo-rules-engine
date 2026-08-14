"""Repository interface. The pipeline depends on this, not on SQLite or
Supabase, so swapping the store is a constructor change."""

from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional, Tuple

from backend.models import HierarchyLevel, User


class Repository(ABC):
    # Which SQL dialect this store speaks. The engine passes it to
    # build_predicates so the five checks are written correctly for the
    # backend without any string translation.
    dialect: str = "sqlite"
    # Reported by /health so the UI shows the store actually in use,
    # not merely the one configured.
    backend_name: str = "sqlite"

    @abstractmethod
    def list_users(self) -> List[User]: ...

    @abstractmethod
    def get_user(self, user_id: str) -> Optional[User]: ...

    @abstractmethod
    def list_hierarchy(self, org_id: str) -> List[HierarchyLevel]: ...

    @abstractmethod
    def total_node_count(self, org_id: str) -> int: ...

    @abstractmethod
    def zone2_node_ids(self, org_id: str) -> List[str]: ...

    @abstractmethod
    def run_checks(
        self,
        org_id: str,
        candidate_level_ids: List[str],
        predicates: List[Tuple[str, str, List[Any]]],
        fetch_rows_at_end: bool,
        collect_ids_per_stage: bool,
    ) -> Dict[str, Any]:
        """Execute the five checks as progressive SQL WHERE clauses.

        `predicates` is an ordered list of (check_name, sql_fragment, params).
        Stage k runs with fragments 1..k ANDed together, so the input to
        check k+1 is exactly the output of check k - sequential by
        construction, and executed by the database rather than in Python.

        Only the final surviving rows have their content fetched.
        """
        ...
