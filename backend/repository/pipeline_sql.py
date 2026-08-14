"""
The single-statement form of the pipeline tail.

`run_checks` executes the five checks as seven separate round trips (one
COUNT per stage, plus the final fetch). That is clear to read and it is what
the SQLite path used for a long time, but against a hosted database every one
of those is a network RTT. This module expresses exactly the same logic as one
statement so the whole tail costs a single round trip.

The checks remain sequential and remain visible: each is its own CTE, and
c(n) selects FROM c(n-1). Nothing is merged into a single flat WHERE.
"""

from typing import Any, Dict, List, Tuple

Predicate = Tuple[str, str, List[Any]]

CHECK_CTE = ["c1_isolation", "c2_compliance", "c3_permission",
             "c4_temporal", "c5_derivability"]

# The columns the five checks need to make their decisions. Deliberately NOT
# `n.*`: `content` and `title` are the sensitive payload, and carrying them
# through the chain would mean the database materialises the content of nodes
# that checks 2-5 are about to discard. The chain moves metadata only; content
# is joined back on at the very end, for survivors alone.
FILTER_COLUMNS_COMMON = (
    "id", "org_id", "hierarchy_level_id", "hierarchy_level", "zone", "status",
    "department", "superseded_by", "valid_until", "derivability_score",
)
# Compliance reads a different column per dialect: SQLite has no array type,
# so tags are denormalised into `required_tags`.
FILTER_COLUMNS_SQLITE = FILTER_COLUMNS_COMMON + ("required_tags",)
FILTER_COLUMNS_POSTGRES = FILTER_COLUMNS_COMMON + ("compliance_tags",)


def filter_columns(dialect: str):
    return (FILTER_COLUMNS_POSTGRES if dialect == "postgres"
            else FILTER_COLUMNS_SQLITE)


def build(
    org_id: str,
    level_ids: List[str],
    zone2_enabled: bool,
    predicates: List[Predicate],
    placeholder: str = "?",
    dialect: str = "sqlite",
) -> Tuple[str, List[Any]]:
    """Return (sql, params) for the whole tail.

    Shape:
        bfs      -> nodes on tiers BFS reached
        pool     -> bfs UNION zone2      (UNION dedupes: a global node that is
                                          also on the ancestor path appears once)
        c1..c5   -> each check filtering the previous check's output
        counts   -> COUNT(*) per stage, from the same CTEs
        SELECT   -> counts LEFT JOIN c5, so the funnel survives an empty set
    """
    ph = placeholder
    params: List[Any] = []

    def marks(values):
        params.extend(values)
        return ",".join([ph] * len(values))

    # --- pool: BFS reach, then Zone 2 injected on top -------------------
    parts = [f"SELECT COUNT(*) FROM knowledge_nodes WHERE org_id = {ph}"]
    params.append(org_id)
    total_sql = parts[0]

    if level_ids:
        bfs_sql = (f"SELECT id FROM knowledge_nodes WHERE org_id = {ph} "
                   f"AND hierarchy_level_id IN ({{}})")
        params.append(org_id)
        bfs_sql = bfs_sql.format(marks(level_ids))
    else:
        bfs_sql = "SELECT id FROM knowledge_nodes WHERE 1 = 0"

    if zone2_enabled:
        # Selected here rather than fetched first: that is one fewer round
        # trip, and zone is a property of the node so the database can pick
        # them without help.
        z2_sql = (f"SELECT id FROM knowledge_nodes "
                  f"WHERE org_id = {ph} AND zone = 2")
        params.append(org_id)
        pool_sql = "SELECT id FROM bfs UNION SELECT id FROM zone2"
    else:
        z2_sql = "SELECT id FROM knowledge_nodes WHERE 1 = 0"
        pool_sql = "SELECT id FROM bfs"

    # --- the five checks, each reading the previous one -----------------
    ctes = [
        f"total AS ({total_sql})",
        f"bfs AS ({bfs_sql})",
        f"zone2 AS ({z2_sql})",
        f"pool AS ({pool_sql})",
    ]

    # Metadata only - see FILTER_COLUMNS_COMMON.
    cols = ", ".join(f"n.{c}" for c in filter_columns(dialect))
    previous = (f"SELECT {cols} FROM knowledge_nodes n "
                "JOIN pool p ON p.id = n.id")
    for i, (_name, fragment, frag_params) in enumerate(predicates):
        source = previous if i == 0 else f"SELECT * FROM {CHECK_CTE[i - 1]}"
        where = f" WHERE {fragment}" if fragment else ""
        ctes.append(f"{CHECK_CTE[i]} AS ({source}{where})")
        params.extend(frag_params)

    counts = ", ".join(
        [f"(SELECT * FROM total) AS total_nodes",
         "(SELECT COUNT(*) FROM bfs) AS after_bfs",
         "(SELECT COUNT(*) FROM pool) AS after_zone2"]
        + [f"(SELECT COUNT(*) FROM {c}) AS after_{c.split('_', 1)[1]}"
           for c in CHECK_CTE]
    )
    ctes.append(f"counts AS (SELECT {counts})")

    # Content is read HERE and only here: joined to the survivors of check 5.
    # A node excluded by any check never has its content touched.
    survivors = ("SELECT n.* FROM knowledge_nodes n "
                 f"JOIN {CHECK_CTE[-1]} s ON s.id = n.id")

    sql = (
        "WITH " + ",\n     ".join(ctes) + "\n"
        "SELECT counts.*, node.* FROM counts "
        f"LEFT JOIN ({survivors}) AS node ON 1 = 1 "
        "ORDER BY node.importance DESC, node.id"
    )
    return sql, params


def split_rows(rows: List[Dict[str, Any]]) -> Tuple[Dict[str, int], List[Dict]]:
    """Separate the repeated funnel columns from the candidate rows."""
    count_cols = ["total_nodes", "after_bfs", "after_zone2",
                  "after_isolation", "after_compliance", "after_permission",
                  "after_temporal", "after_derivability"]
    if not rows:
        return {c: 0 for c in count_cols}, []
    funnel = {c: int(rows[0][c] or 0) for c in count_cols}
    nodes = [r for r in rows if r.get("id") is not None]
    return funnel, nodes
