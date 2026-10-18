"""The mutant corpus used for the mutation-kill-rate evaluation.

Each entry pairs a hand-written "reference" query with either:

* a **mutant**: a plausible, realistic rewrite that changes behavior in
  one specific way a reviewer could easily miss, with a human label of
  *why* it differs, or
* a **safe rewrite**: a syntactically different but behaviorally
  identical query, used to measure the oracle's false-positive rate.

Hand-written, labeled mutants are a standard mutation-testing practice
(sometimes called "first-order realistic mutants") and are preferred
here over automatic AST mutation: automatic SQL mutators routinely
produce syntactically invalid or semantically absurd queries that would
make the kill-rate numbers meaningless. Every mutant below is a change a
real reviewer approving a real pull request could plausibly wave through.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from sql_equivalence_guard.schema import ColumnSpec, TableSpec

Kind = Literal["mutant", "safe_rewrite", "conditional_rewrite"]
"""``conditional_rewrite`` is for a pair that is equivalent only under an
implicit assumption (documented in that case's description) which the
edge-case generator can violate. It exists because one such pair, found
during this project's own development rather than designed in, turned
out to be the most interesting result in the corpus: see
``q3_safe_rank_rewrite`` below."""


@dataclass(frozen=True)
class CaseSpec:
    """One (reference, candidate) query pair plus the ground-truth label."""

    case_id: str
    base_query: str
    reference_sql: str
    candidate_sql: str
    kind: Kind
    description: str
    table_specs: dict[str, TableSpec]
    edge_case_hint: str


# ---------------------------------------------------------------------------
# Q1: daily active users, DISTINCT vs GROUP BY vs a missing DISTINCT
# ---------------------------------------------------------------------------

_EVENTS = TableSpec(
    "events",
    (
        ColumnSpec("event_day", "date"),
        ColumnSpec("user_id", "int", key_pool_size=12, low=1, high=200),
    ),
)

Q1_REFERENCE = """
    SELECT event_day, COUNT(DISTINCT user_id) AS active_users
    FROM events
    GROUP BY event_day
"""

Q1_MUTANT_DROP_DISTINCT = """
    SELECT event_day, COUNT(user_id) AS active_users
    FROM events
    GROUP BY event_day
"""

Q1_SAFE_REWRITE = """
    SELECT event_day, COUNT(*) AS active_users
    FROM (SELECT DISTINCT event_day, user_id FROM events) AS deduped
    GROUP BY event_day
"""

# ---------------------------------------------------------------------------
# Q2: order revenue net of discount, LEFT JOIN vs INNER JOIN
# ---------------------------------------------------------------------------

_ORDERS = TableSpec(
    "orders",
    (
        ColumnSpec("order_id", "int", key_pool_size=None, low=1, high=100_000),
        ColumnSpec("amount", "double", low=5, high=500),
    ),
)
_DISCOUNTS = TableSpec(
    "discounts",
    (
        ColumnSpec("order_id", "int", key_pool_size=30, low=1, high=100_000),
        ColumnSpec("discount", "double", low=0, high=50),
    ),
)

Q2_REFERENCE = """
    SELECT COALESCE(SUM(o.amount - COALESCE(d.discount, 0)), 0) AS net_revenue
    FROM orders o
    LEFT JOIN discounts d ON o.order_id = d.order_id
"""

Q2_MUTANT_INNER_JOIN = """
    SELECT COALESCE(SUM(o.amount - COALESCE(d.discount, 0)), 0) AS net_revenue
    FROM orders o
    JOIN discounts d ON o.order_id = d.order_id
"""

Q2_SAFE_REWRITE = """
    SELECT COALESCE(SUM(o.amount) - SUM(COALESCE(d.discount, 0)), 0) AS net_revenue
    FROM orders o
    LEFT JOIN discounts d ON o.order_id = d.order_id
"""

# ---------------------------------------------------------------------------
# Q3: top incident per day by severity, ORDER BY direction / PARTITION BY
# ---------------------------------------------------------------------------

_INCIDENTS = TableSpec(
    "incidents",
    (
        ColumnSpec("incident_day", "date"),
        ColumnSpec("incident_id", "int", low=1, high=100_000),
        ColumnSpec("severity", "int", low=1, high=5, boundary_values=(3,)),
    ),
)

Q3_REFERENCE = """
    SELECT incident_day, incident_id, severity
    FROM (
        SELECT *, ROW_NUMBER() OVER (
            PARTITION BY incident_day ORDER BY severity DESC, incident_id ASC
        ) AS rn
        FROM incidents
    )
    WHERE rn = 1
"""

Q3_MUTANT_WRONG_DIRECTION = """
    SELECT incident_day, incident_id, severity
    FROM (
        SELECT *, ROW_NUMBER() OVER (
            PARTITION BY incident_day ORDER BY severity ASC, incident_id ASC
        ) AS rn
        FROM incidents
    )
    WHERE rn = 1
"""

Q3_MUTANT_DROP_PARTITION = """
    SELECT incident_day, incident_id, severity
    FROM (
        SELECT *, ROW_NUMBER() OVER (
            ORDER BY severity DESC, incident_id ASC
        ) AS rn
        FROM incidents
    )
    WHERE rn = 1
"""

Q3_SAFE_REWRITE = """
    SELECT incident_day, incident_id, severity
    FROM (
        SELECT *, RANK() OVER (
            PARTITION BY incident_day ORDER BY severity DESC, incident_id ASC
        ) AS rn
        FROM incidents
    )
    WHERE rn = 1
"""

# ---------------------------------------------------------------------------
# Q4: SLA compliance threshold, inclusive vs exclusive boundary
# ---------------------------------------------------------------------------

_JOBS = TableSpec(
    "jobs",
    (
        ColumnSpec("job_id", "int", low=1, high=100_000),
        ColumnSpec("duration_minutes", "int", low=0, high=600, boundary_values=(30,)),
    ),
)

Q4_REFERENCE = """
    SELECT COUNT(*) AS within_sla
    FROM jobs
    WHERE duration_minutes <= 30
"""

Q4_MUTANT_EXCLUSIVE_BOUNDARY = """
    SELECT COUNT(*) AS within_sla
    FROM jobs
    WHERE duration_minutes < 30
"""

Q4_SAFE_REWRITE = """
    SELECT COUNT(*) AS within_sla
    FROM jobs
    WHERE NOT (duration_minutes > 30)
"""

# ---------------------------------------------------------------------------
# Q5: average retry count, NULL-as-zero vs NULL-excluded semantics
# ---------------------------------------------------------------------------

_RETRIES = TableSpec(
    "task_runs",
    (
        ColumnSpec("task_run_id", "int", low=1, high=100_000),
        ColumnSpec("retry_count", "int", nullable=True, low=0, high=5),
    ),
)

Q5_REFERENCE = """
    SELECT AVG(COALESCE(retry_count, 0)) AS avg_retries
    FROM task_runs
"""

Q5_MUTANT_DROP_COALESCE = """
    SELECT AVG(retry_count) AS avg_retries
    FROM task_runs
"""

Q5_SAFE_REWRITE = """
    SELECT SUM(COALESCE(retry_count, 0)) * 1.0 / COUNT(*) AS avg_retries
    FROM task_runs
"""


def _case(case_id, base, ref, cand, kind, desc, specs, hint) -> CaseSpec:
    return CaseSpec(
        case_id=case_id,
        base_query=base,
        reference_sql=ref,
        candidate_sql=cand,
        kind=kind,
        description=desc,
        table_specs=specs,
        edge_case_hint=hint,
    )


CASES: list[CaseSpec] = [
    _case(
        "q1_drop_distinct", "q1", Q1_REFERENCE, Q1_MUTANT_DROP_DISTINCT, "mutant",
        "DISTINCT silently dropped: double-counts a user active twice in one day.",
        {"events": _EVENTS}, "needs duplicate (event_day, user_id) rows: raise key_pool_size pressure",
    ),
    _case(
        "q1_safe_groupby_rewrite", "q1", Q1_REFERENCE, Q1_SAFE_REWRITE, "safe_rewrite",
        "DISTINCT expressed via a nested dedup subquery instead of COUNT(DISTINCT ...).",
        {"events": _EVENTS}, "none: should never be killed",
    ),
    _case(
        "q2_inner_join", "q2", Q2_REFERENCE, Q2_MUTANT_INNER_JOIN, "mutant",
        "LEFT JOIN narrowed to INNER JOIN: orders with no matching discount row vanish.",
        {"orders": _ORDERS, "discounts": _DISCOUNTS}, "needs orders with no matching discount row",
    ),
    _case(
        "q2_safe_sum_distribution", "q2", Q2_REFERENCE, Q2_SAFE_REWRITE, "safe_rewrite",
        "SUM(a - b) rewritten as SUM(a) - SUM(b); arithmetically identical over the same rows.",
        {"orders": _ORDERS, "discounts": _DISCOUNTS}, "none: should never be killed",
    ),
    _case(
        "q3_wrong_tiebreak_direction", "q3", Q3_REFERENCE, Q3_MUTANT_WRONG_DIRECTION, "mutant",
        "ORDER BY severity DESC flipped to ASC: picks the least severe incident of the day instead of the most severe.",
        {"incidents": _INCIDENTS}, "needs more than one severity value on the same day",
    ),
    _case(
        "q3_drop_partition", "q3", Q3_REFERENCE, Q3_MUTANT_DROP_PARTITION, "mutant",
        "PARTITION BY incident_day removed: ranks globally, returning only one incident total instead of one per day.",
        {"incidents": _INCIDENTS}, "needs more than one distinct incident_day",
    ),
    _case(
        "q3_safe_rank_rewrite", "q3", Q3_REFERENCE, Q3_SAFE_REWRITE, "conditional_rewrite",
        "ROW_NUMBER replaced by RANK, reasoned to be identical because the ORDER BY key "
        "(severity, incident_id) is unique within each partition. That reasoning holds only "
        "when no two rows are exact duplicates of each other: ROW_NUMBER breaks a tie "
        "between two byte-identical rows arbitrarily and keeps exactly one, while RANK "
        "assigns both the same rank and keeps both, so rn = 1 returns two rows instead of "
        "one. This project's own edge-case generator (which deliberately injects exact "
        "duplicate rows, modeling an upstream retry or replay bug) found this during "
        "development; it was not designed in as a mutant. See README / ARTICLE for why "
        "this is the corpus's most interesting result.",
        {"incidents": _INCIDENTS}, "needs an exact duplicate full row: caught only when the generator injects one",
    ),
    _case(
        "q4_exclusive_boundary", "q4", Q4_REFERENCE, Q4_MUTANT_EXCLUSIVE_BOUNDARY, "mutant",
        "<=30 narrowed to <30: jobs that take exactly 30 minutes flip from compliant to non-compliant.",
        {"jobs": _JOBS}, "needs duration_minutes == 30 exactly: a classic boundary-value miss",
    ),
    _case(
        "q4_safe_demorgan_rewrite", "q4", Q4_REFERENCE, Q4_SAFE_REWRITE, "safe_rewrite",
        "<=30 rewritten as NOT (>30); logically identical by De Morgan's law.",
        {"jobs": _JOBS}, "none: should never be killed",
    ),
    _case(
        "q5_drop_coalesce", "q5", Q5_REFERENCE, Q5_MUTANT_DROP_COALESCE, "mutant",
        "COALESCE(retry_count, 0) dropped: AVG silently excludes NULL rows from both the sum and the denominator instead of treating them as zero retries.",
        {"task_runs": _RETRIES}, "needs NULL retry_count rows",
    ),
    _case(
        "q5_safe_division_rewrite", "q5", Q5_REFERENCE, Q5_SAFE_REWRITE, "safe_rewrite",
        "AVG(COALESCE(x,0)) rewritten as explicit SUM/COUNT; identical once NULLs are coalesced before the sum.",
        {"task_runs": _RETRIES}, "none: should never be killed",
    ),
]
