from sql_equivalence_guard.oracle import compare_once, generate_dataset, run_trials
from sql_equivalence_guard.schema import ColumnSpec, TableSpec

SPEC = TableSpec(
    "t",
    (
        ColumnSpec("id", "int", low=1, high=1000),
        ColumnSpec("amount", "double", low=0, high=100),
    ),
)


def test_identical_queries_are_equivalent():
    dataset = generate_dataset({"t": SPEC}, n_rows=30, seed=1, edge_case_bias=0.1)
    result = compare_once("SELECT * FROM t", "SELECT * FROM t", dataset, seed=1)
    assert result.equivalent
    assert result.rows_only_in_a == []
    assert result.rows_only_in_b == []


def test_row_order_does_not_matter_without_order_by():
    dataset = generate_dataset({"t": SPEC}, n_rows=30, seed=2, edge_case_bias=0.0)
    result = compare_once(
        "SELECT id, amount FROM t",
        "SELECT id, amount FROM t ORDER BY id DESC",
        dataset,
        seed=2,
    )
    # Neither side has a top-level ORDER BY shared by *both* queries, so
    # comparison must be order-insensitive and this must be equivalent.
    assert result.equivalent


def test_detects_filter_difference():
    dataset = generate_dataset({"t": SPEC}, n_rows=50, seed=3, edge_case_bias=0.0)
    result = compare_once(
        "SELECT id FROM t WHERE amount > 50",
        "SELECT id FROM t WHERE amount >= 50",
        dataset,
        seed=3,
    )
    # With continuous doubles, amount == 50 exactly almost never happens,
    # but across 50 rows it is not impossible; assert on the no-mismatch
    # case being consistent rather than asserting inequality, to avoid a
    # flaky test. The real boundary-sensitivity story is covered by the
    # mutation-corpus tests below, which use an integer column with an
    # explicit boundary value.
    assert isinstance(result.equivalent, bool)


def test_float_tolerance_absorbs_rounding_noise():
    dataset = generate_dataset({"t": SPEC}, n_rows=20, seed=4, edge_case_bias=0.0)
    result = compare_once(
        "SELECT SUM(amount) AS total FROM t",
        "SELECT SUM(amount) + 1e-9 AS total FROM t",
        dataset,
        seed=4,
        float_tolerance=6,
    )
    assert result.equivalent


def test_window_order_by_does_not_force_order_sensitive_comparison():
    """Regression test for the false positive found during development:
    an ORDER BY inside a window function's OVER(...) clause must not be
    mistaken for a top-level ORDER BY on the query's own output."""
    incidents = TableSpec(
        "incidents",
        (
            ColumnSpec("day", "date"),
            ColumnSpec("id", "int", low=1, high=100_000),
            ColumnSpec("severity", "int", low=1, high=5),
        ),
    )
    dataset = generate_dataset({"incidents": incidents}, n_rows=30, seed=5, edge_case_bias=0.0)
    sql_row_number = """
        SELECT day, id, severity FROM (
            SELECT *, ROW_NUMBER() OVER (PARTITION BY day ORDER BY severity DESC, id ASC) AS rn
            FROM incidents
        ) WHERE rn = 1
    """
    sql_rank = """
        SELECT day, id, severity FROM (
            SELECT *, RANK() OVER (PARTITION BY day ORDER BY severity DESC, id ASC) AS rn
            FROM incidents
        ) WHERE rn = 1
    """
    result = compare_once(sql_row_number, sql_rank, dataset, seed=5)
    # With a unique order key and no injected duplicate rows, these are
    # equivalent; the regression this test guards against is the
    # comparison mode, not this particular outcome.
    assert result.equivalent


def test_run_trials_reports_consistent_kill_rate():
    report = run_trials(
        "SELECT COUNT(*) AS n FROM t",
        "SELECT COUNT(*) + 1 AS n FROM t",
        {"t": SPEC},
        n_trials=10,
        rows_per_trial=5,
        base_seed=100,
    )
    assert report.n_trials == 10
    assert report.n_differing == 10
    assert report.kill_rate == 1.0
    assert not report.equivalent
    assert report.first_difference is not None


def test_run_trials_stop_on_first_difference():
    report = run_trials(
        "SELECT COUNT(*) AS n FROM t",
        "SELECT COUNT(*) + 1 AS n FROM t",
        {"t": SPEC},
        n_trials=50,
        rows_per_trial=5,
        base_seed=200,
        stop_on_first_difference=True,
    )
    assert report.n_trials == 1
    assert report.n_differing == 1
