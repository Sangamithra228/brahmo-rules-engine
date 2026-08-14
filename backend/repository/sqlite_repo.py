"""
SQLite-backed repository.

Chosen as the default so the demo runs with zero installs and zero network.
`SupabaseRepository` implements the same interface against PostgreSQL and is a
one-line swap; the SQL predicates are shared between the two.

Array columns (compliance_tags, parent_ids) do not exist in SQLite. They are
stored as JSON text, plus a denormalised `required_tags` column shaped like
',MNPI,CONFIDENTIAL,' so the compliance check stays a pure SQL predicate
rather than something Python has to post-filter. PostgreSQL uses native
TEXT[] with a GIN index and the `&&` overlap operator - see
supabase/schema.sql.
"""

import json
import os
import sqlite3
from typing import Any, Dict, List, Optional, Tuple

from backend.data import seed_data
from backend.models import HierarchyLevel, KnowledgeNode, User
from backend.repository.base import Repository

DEFAULT_DB_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "brahmo.db")


def _tag_blob(tags: List[str]) -> str:
    return "," + ",".join(sorted(tags)) + "," if tags else ","


class SQLiteRepository(Repository):
    dialect = "sqlite"
    backend_name = "sqlite"

    def __init__(self, db_path: str = None):
        self.db_path = os.path.abspath(db_path or DEFAULT_DB_PATH)
        self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row

    # ---------------- schema + seed ----------------
    def initialise(self) -> None:
        c = self._conn
        c.executescript(
            """
            DROP TABLE IF EXISTS audit_log;
            DROP TABLE IF EXISTS edges;
            DROP TABLE IF EXISTS knowledge_nodes;
            DROP TABLE IF EXISTS users;
            DROP TABLE IF EXISTS hierarchy_levels;
            DROP TABLE IF EXISTS organizations;

            CREATE TABLE organizations (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                segment TEXT NOT NULL,
                config TEXT DEFAULT '{}'
            );

            CREATE TABLE hierarchy_levels (
                id TEXT PRIMARY KEY,
                org_id TEXT NOT NULL REFERENCES organizations(id),
                level_number INTEGER NOT NULL CHECK (level_number BETWEEN 1 AND 15),
                level_name TEXT NOT NULL,
                department TEXT,
                parent_ids TEXT NOT NULL DEFAULT '[]',
                zone INTEGER NOT NULL DEFAULT 1 CHECK (zone IN (1,2,3))
            );

            CREATE TABLE knowledge_nodes (
                id TEXT PRIMARY KEY,
                org_id TEXT NOT NULL REFERENCES organizations(id),
                hierarchy_level_id TEXT NOT NULL REFERENCES hierarchy_levels(id),
                type TEXT NOT NULL CHECK (type IN
                    ('CONSTRAINT','DECISION','ANTI_PATTERN','FACT')),
                title TEXT NOT NULL,
                content TEXT NOT NULL,
                importance REAL NOT NULL CHECK (importance BETWEEN 0.0 AND 1.0),
                zone INTEGER NOT NULL DEFAULT 1 CHECK (zone IN (1,2,3)),
                status TEXT NOT NULL DEFAULT 'ACTIVE' CHECK (status IN
                    ('ACTIVE','REVIEW_REQUIRED','SUPERSEDED','EXPIRED','LEGAL_HOLD')),
                derivability_score REAL NOT NULL DEFAULT 0.0
                    CHECK (derivability_score BETWEEN 0.0 AND 1.0),
                compliance_tags TEXT NOT NULL DEFAULT '[]',
                required_tags TEXT NOT NULL DEFAULT ',',
                valid_until TEXT,
                superseded_by TEXT,
                department TEXT,
                -- Denormalised from hierarchy_levels.level_number so the
                -- permission predicate is an indexed integer compare instead
                -- of a join. The graph is static; this is maintained on write.
                hierarchy_level INTEGER NOT NULL DEFAULT 0
            );

            CREATE TABLE edges (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source_id TEXT NOT NULL REFERENCES knowledge_nodes(id),
                target_id TEXT NOT NULL REFERENCES knowledge_nodes(id),
                edge_type TEXT NOT NULL CHECK (edge_type IN
                    ('SUPPORTS','CONTRADICTS','SUPERSEDES','DERIVED_FROM','REQUIRES')),
                confidence REAL DEFAULT 1.0
            );

            CREATE TABLE users (
                id TEXT PRIMARY KEY,
                org_id TEXT NOT NULL REFERENCES organizations(id),
                name TEXT NOT NULL,
                role TEXT NOT NULL,
                department TEXT NOT NULL,
                ceiling_level INTEGER NOT NULL CHECK (ceiling_level BETWEEN 1 AND 15),
                write_ceiling INTEGER,
                compliance_clearance TEXT NOT NULL DEFAULT '[]',
                status TEXT DEFAULT 'ACTIVE'
            );

            CREATE TABLE audit_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                node_id TEXT,
                action TEXT NOT NULL,
                actor_id TEXT,
                org_id TEXT NOT NULL,
                timestamp TEXT DEFAULT CURRENT_TIMESTAMP
            );

            CREATE INDEX idx_nodes_org ON knowledge_nodes(org_id);
            CREATE INDEX idx_nodes_zone ON knowledge_nodes(zone);
            CREATE INDEX idx_nodes_status ON knowledge_nodes(status);
            CREATE INDEX idx_nodes_dept ON knowledge_nodes(department);
            CREATE INDEX idx_nodes_hierarchy ON knowledge_nodes(hierarchy_level_id);
            CREATE INDEX idx_nodes_deriv ON knowledge_nodes(derivability_score);
            CREATE INDEX idx_nodes_level ON knowledge_nodes(hierarchy_level);
            CREATE INDEX idx_nodes_reqtags ON knowledge_nodes(required_tags);
            CREATE INDEX idx_hierarchy_org ON hierarchy_levels(org_id);
            """
        )
        c.commit()

    def seed(self) -> None:
        c = self._conn
        o = seed_data.ORGANIZATION
        c.execute(
            "INSERT INTO organizations (id,name,segment,config) VALUES (?,?,?,?)",
            (o["id"], o["name"], o["segment"], json.dumps(o["config"])),
        )
        for (lid, num, name, dept, parents, zone) in seed_data.HIERARCHY_LEVELS:
            c.execute(
                "INSERT INTO hierarchy_levels "
                "(id,org_id,level_number,level_name,department,parent_ids,zone) "
                "VALUES (?,?,?,?,?,?,?)",
                (lid, "supra", num, name, dept, json.dumps(parents), zone),
            )
        for (uid, name, role, dept, ceil, wceil, clr) in seed_data.USERS:
            c.execute(
                "INSERT INTO users (id,org_id,name,role,department,ceiling_level,"
                "write_ceiling,compliance_clearance) VALUES (?,?,?,?,?,?,?,?)",
                (uid, "supra", name, role, dept, ceil, wceil, json.dumps(clr)),
            )
        level_number = {l[0]: l[1] for l in seed_data.HIERARCHY_LEVELS}
        for n in seed_data.KNOWLEDGE_NODES:
            (nid, hlid, ntype, title, content, imp, zone, status, deriv,
             tags, dept) = n
            c.execute(
                "INSERT INTO knowledge_nodes (id,org_id,hierarchy_level_id,type,"
                "title,content,importance,zone,status,derivability_score,"
                "compliance_tags,required_tags,department,hierarchy_level) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (nid, "supra", hlid, ntype, title, content, imp, zone, status,
                 deriv, json.dumps(tags), _tag_blob(tags), dept,
                 level_number[hlid]),
            )
        for (src, tgt, etype) in seed_data.EDGES:
            c.execute(
                "INSERT INTO edges (source_id,target_id,edge_type) VALUES (?,?,?)",
                (src, tgt, etype),
            )
        c.commit()

    def is_seeded(self, org_id: str = "supra") -> bool:
        """True when the schema exists and carries rows. Used by the factory
        to decide whether the local fallback needs building."""
        try:
            return self.total_node_count(org_id) > 0
        except sqlite3.OperationalError:
            return False

    # ---------------- reads ----------------
    def list_users(self) -> List[User]:
        rows = self._conn.execute(
            "SELECT * FROM users ORDER BY ceiling_level, name"
        ).fetchall()
        return [self._user(r) for r in rows]

    def get_user(self, user_id: str) -> Optional[User]:
        r = self._conn.execute(
            "SELECT * FROM users WHERE id = ?", (user_id,)
        ).fetchone()
        return self._user(r) if r else None

    def list_hierarchy(self, org_id: str) -> List[HierarchyLevel]:
        rows = self._conn.execute(
            "SELECT * FROM hierarchy_levels WHERE org_id = ? ORDER BY level_number, id",
            (org_id,),
        ).fetchall()
        return [
            HierarchyLevel(
                id=r["id"], org_id=r["org_id"], level_number=r["level_number"],
                level_name=r["level_name"], department=r["department"],
                parent_ids=json.loads(r["parent_ids"]), zone=r["zone"],
            )
            for r in rows
        ]

    def total_node_count(self, org_id: str) -> int:
        return self._conn.execute(
            "SELECT COUNT(*) c FROM knowledge_nodes WHERE org_id = ?", (org_id,)
        ).fetchone()["c"]

    def zone2_node_ids(self, org_id: str) -> List[str]:
        """Zone 2 is a property of the NODE, not of its hierarchy level.
        HL-GLOBAL also hosts a zone-1 node (N-D03), which must NOT be
        injected."""
        rows = self._conn.execute(
            "SELECT id FROM knowledge_nodes WHERE org_id = ? AND zone = 2 "
            "ORDER BY id",
            (org_id,),
        ).fetchall()
        return [r["id"] for r in rows]

    def count_candidates(
        self, org_id: str, level_ids: List[str], extra_node_ids: List[str]
    ) -> int:
        where, params = self._candidate_where(org_id, level_ids, extra_node_ids)
        if where is None:
            return 0
        return self._conn.execute(
            f"SELECT COUNT(*) c FROM knowledge_nodes WHERE {where}", params
        ).fetchone()["c"]

    @staticmethod
    def _candidate_where(org_id, level_ids, extra_node_ids):
        clauses, params = [], [org_id]
        if level_ids:
            clauses.append(
                "hierarchy_level_id IN (%s)" % ",".join("?" * len(level_ids))
            )
            params += list(level_ids)
        if extra_node_ids:
            clauses.append("id IN (%s)" % ",".join("?" * len(extra_node_ids)))
            params += list(extra_node_ids)
        if not clauses:
            return None, []
        return "org_id = ? AND (%s)" % " OR ".join(clauses), params

    def run_pipeline_single_query(self, org_id, candidate_level_ids,
                                  zone2_enabled, predicates):
        from backend.repository import pipeline_sql

        sql, params = pipeline_sql.build(
            org_id, candidate_level_ids, zone2_enabled, predicates,
            placeholder="?", dialect="sqlite")
        rows = [dict(r) for r in self._conn.execute(sql, params).fetchall()]
        funnel, node_rows = pipeline_sql.split_rows(rows)
        return {"funnel": funnel, "rows": [self._node_from_dict(r) for r in node_rows]}

    @staticmethod
    def _node_from_dict(r: dict) -> KnowledgeNode:
        return KnowledgeNode(
            id=r["id"], org_id=r["org_id"],
            hierarchy_level_id=r["hierarchy_level_id"], type=r["type"],
            title=r["title"], content=r["content"], importance=r["importance"],
            zone=r["zone"], status=r["status"],
            derivability_score=r["derivability_score"],
            compliance_tags=json.loads(r["compliance_tags"]),
            department=r["department"], valid_until=r["valid_until"],
            superseded_by=r["superseded_by"],
            hierarchy_level=r["hierarchy_level"])

    # ---------------- the five checks ----------------
    def run_checks(
        self,
        org_id: str,
        candidate_level_ids: List[str],
        predicates: List[Tuple[str, str, List[Any]]],
        fetch_rows_at_end: bool = True,
        collect_ids_per_stage: bool = False,
        extra_node_ids: List[str] = None,
    ) -> Dict[str, Any]:
        """Progressive WHERE-clause execution.

        Stage k = stages 1..k ANDed. The count after stage k is the input to
        stage k+1, which is what "sequential" means here - and every stage is
        evaluated by the database, so a node excluded at check 2 never has its
        content read at check 3, let alone shipped to Python.
        """
        result: Dict[str, Any] = {"stages": [], "rows": []}

        base_where, base_params = self._candidate_where(
            org_id, candidate_level_ids, extra_node_ids or []
        )
        if base_where is None:
            for (name, _sql, _p) in predicates:
                result["stages"].append({"check": name, "count": 0, "ids": []})
            return result

        where_parts: List[str] = [base_where]
        params: List[Any] = list(base_params)

        for (name, sql_fragment, frag_params) in predicates:
            if sql_fragment:
                where_parts.append(f"({sql_fragment})")
                params.extend(frag_params)
            where_sql = " AND ".join(where_parts)

            if collect_ids_per_stage:
                rows = self._conn.execute(
                    f"SELECT id FROM knowledge_nodes WHERE {where_sql}", params
                ).fetchall()
                result["stages"].append(
                    {"check": name, "count": len(rows), "ids": [r["id"] for r in rows]}
                )
            else:
                cnt = self._conn.execute(
                    f"SELECT COUNT(*) c FROM knowledge_nodes WHERE {where_sql}",
                    params,
                ).fetchone()["c"]
                result["stages"].append({"check": name, "count": cnt, "ids": None})

        if fetch_rows_at_end:
            where_sql = " AND ".join(where_parts)
            rows = self._conn.execute(
                f"""SELECT * FROM knowledge_nodes
                    WHERE {where_sql}
                    ORDER BY importance DESC, id""",
                params,
            ).fetchall()
            result["rows"] = [self._node(r) for r in rows]

        return result

    # ---------------- helpers ----------------
    @staticmethod
    def _user(r: sqlite3.Row) -> User:
        return User(
            id=r["id"], org_id=r["org_id"], name=r["name"], role=r["role"],
            department=r["department"], ceiling_level=r["ceiling_level"],
            write_ceiling=r["write_ceiling"],
            compliance_clearance=json.loads(r["compliance_clearance"]),
            status=r["status"],
        )

    @staticmethod
    def _node(r: sqlite3.Row) -> KnowledgeNode:
        return KnowledgeNode(
            id=r["id"], org_id=r["org_id"],
            hierarchy_level_id=r["hierarchy_level_id"], type=r["type"],
            title=r["title"], content=r["content"], importance=r["importance"],
            zone=r["zone"], status=r["status"],
            derivability_score=r["derivability_score"],
            compliance_tags=json.loads(r["compliance_tags"]),
            department=r["department"], valid_until=r["valid_until"],
            superseded_by=r["superseded_by"],
            hierarchy_level=r["hierarchy_level"],
        )

    def titles_for(self, ids: List[str]) -> Dict[str, str]:
        """Titles only, for the operator audit trail. Never content."""
        if not ids:
            return {}
        q = ",".join("?" * len(ids))
        rows = self._conn.execute(
            f"SELECT id,title FROM knowledge_nodes WHERE id IN ({q})", ids
        ).fetchall()
        return {r["id"]: r["title"] for r in rows}

    def close(self) -> None:
        self._conn.close()
