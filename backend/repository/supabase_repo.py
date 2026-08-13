"""
Supabase / PostgreSQL repository.

Same interface as SQLiteRepository, so swapping stores is one line in
backend/main.py. Requires `pip install supabase psycopg[binary]` and a
populated .env; the SQLite path is the default so the demo needs neither.

The predicates are shared - the only dialect differences are:
  * compliance uses the native array containment operator `<@` against a
    TEXT[] with a GIN index, instead of the `required_tags` LIKE trick SQLite
    needs;
  * placeholders are %s rather than ?.
"""

import json
import os
from typing import Any, Dict, List, Optional, Tuple

from backend.models import HierarchyLevel, KnowledgeNode, User
from backend.repository.base import Repository


class SupabaseRepository(Repository):
    def __init__(self, dsn: str = None):
        import psycopg  # imported lazily so the default path needs no driver

        self.dsn = dsn or os.environ.get("SUPABASE_DB_URL")
        if not self.dsn:
            raise RuntimeError("set SUPABASE_DB_URL (see .env.example)")
        self._conn = psycopg.connect(self.dsn, autocommit=True)

    def _rows(self, sql: str, params: List[Any] = None) -> List[dict]:
        with self._conn.cursor() as cur:
            cur.execute(sql, params or [])
            cols = [c.name for c in cur.description]
            return [dict(zip(cols, r)) for r in cur.fetchall()]

    def list_users(self) -> List[User]:
        return [self._user(r) for r in
                self._rows("SELECT * FROM users ORDER BY ceiling_level, name")]

    def get_user(self, user_id: str) -> Optional[User]:
        r = self._rows("SELECT * FROM users WHERE id = %s", [user_id])
        return self._user(r[0]) if r else None

    def list_hierarchy(self, org_id: str) -> List[HierarchyLevel]:
        return [
            HierarchyLevel(
                id=r["id"], org_id=r["org_id"], level_number=r["level_number"],
                level_name=r["level_name"], department=r["department"],
                parent_ids=list(r["parent_ids"] or []), zone=r["zone"])
            for r in self._rows(
                "SELECT * FROM hierarchy_levels WHERE org_id = %s "
                "ORDER BY level_number, id", [org_id])
        ]

    def total_node_count(self, org_id: str) -> int:
        return self._rows(
            "SELECT COUNT(*) c FROM knowledge_nodes WHERE org_id = %s",
            [org_id])[0]["c"]

    def zone2_node_ids(self, org_id: str) -> List[str]:
        return [r["id"] for r in self._rows(
            "SELECT id FROM knowledge_nodes WHERE org_id = %s AND zone = 2 "
            "ORDER BY id", [org_id])]

    dialect = "postgres"
    backend_name = "supabase"

    @staticmethod
    def _candidate_where(org_id, level_ids, extra_node_ids):
        # NOTE: built by concatenation, never by %-formatting. The '%s' here
        # are psycopg placeholders; running them through Python's % operator
        # consumes them as format specifiers and raises.
        clauses, params = [], [org_id]
        if level_ids:
            clauses.append("hierarchy_level_id = ANY(%s)")
            params.append(list(level_ids))
        if extra_node_ids:
            clauses.append("id = ANY(%s)")
            params.append(list(extra_node_ids))
        if not clauses:
            return None, []
        return "org_id = %s AND (" + " OR ".join(clauses) + ")", params

    def is_seeded(self, org_id: str = "supra") -> bool:
        try:
            return self.total_node_count(org_id) > 0
        except Exception:
            return False

    def count_candidates(self, org_id, level_ids, extra_node_ids) -> int:
        where, params = self._candidate_where(org_id, level_ids, extra_node_ids)
        if where is None:
            return 0
        return self._rows(
            f"SELECT COUNT(*) c FROM knowledge_nodes WHERE {where}", params
        )[0]["c"]

    def run_checks(self, org_id, candidate_level_ids, predicates,
                   fetch_rows_at_end=True, collect_ids_per_stage=False,
                   extra_node_ids=None) -> Dict[str, Any]:
        result = {"stages": [], "rows": []}
        base, base_params = self._candidate_where(
            org_id, candidate_level_ids, extra_node_ids or [])
        if base is None:
            for (name, _s, _p) in predicates:
                result["stages"].append({"check": name, "count": 0, "ids": []})
            return result

        parts, params = [base], list(base_params)
        for (name, frag, frag_params) in predicates:
            if frag:
                # Fragments already arrive in Postgres dialect - the engine
                # asks the repository which dialect it speaks before building
                # them. No string translation happens here.
                parts.append(f"({frag})")
                params.extend(frag_params)
            where = " AND ".join(parts)
            if collect_ids_per_stage:
                rows = self._rows(
                    f"SELECT id FROM knowledge_nodes WHERE {where}", params)
                result["stages"].append(
                    {"check": name, "count": len(rows),
                     "ids": [r["id"] for r in rows]})
            else:
                c = self._rows(
                    f"SELECT COUNT(*) c FROM knowledge_nodes WHERE {where}",
                    params)[0]["c"]
                result["stages"].append({"check": name, "count": c, "ids": None})

        if fetch_rows_at_end:
            where = " AND ".join(parts)
            result["rows"] = [
                self._node(r) for r in self._rows(
                    f"SELECT * FROM knowledge_nodes WHERE {where} "
                    f"ORDER BY importance DESC, id", params)
            ]
        return result

    @staticmethod
    def _user(r: dict) -> User:
        return User(
            id=r["id"], org_id=r["org_id"], name=r["name"], role=r["role"],
            department=r["department"], ceiling_level=r["ceiling_level"],
            write_ceiling=r["write_ceiling"],
            compliance_clearance=list(r["compliance_clearance"] or []),
            status=r.get("status", "ACTIVE"))

    @staticmethod
    def _node(r: dict) -> KnowledgeNode:
        return KnowledgeNode(
            id=r["id"], org_id=r["org_id"],
            hierarchy_level_id=r["hierarchy_level_id"], type=r["type"],
            title=r["title"], content=r["content"],
            importance=float(r["importance"]), zone=r["zone"],
            status=r["status"],
            derivability_score=float(r["derivability_score"]),
            compliance_tags=list(r["compliance_tags"] or []),
            department=r["department"],
            valid_until=str(r["valid_until"]) if r.get("valid_until") else None,
            superseded_by=r.get("superseded_by"),
            hierarchy_level=r["hierarchy_level"])

    def titles_for(self, ids: List[str]) -> Dict[str, str]:
        if not ids:
            return {}
        return {r["id"]: r["title"] for r in self._rows(
            "SELECT id,title FROM knowledge_nodes WHERE id = ANY(%s)", [ids])}
