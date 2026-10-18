"""Smoke tests over the whole mutant corpus: fast, few trials, no bias sweep.

The honest, slow mutation-kill-rate sweep lives in eval/run_eval.py and
its output in eval/results.json; these tests exist only to catch a
broken query (syntax error, schema mismatch) in CI, not to re-derive the
headline numbers.
"""

import pytest

from sql_equivalence_guard.mutations import CASES
from sql_equivalence_guard.oracle import run_trials

N_TRIALS = 30
ROWS_PER_TRIAL = 40
BIAS = 0.3
SEED = 999


@pytest.mark.parametrize("case", CASES, ids=[c.case_id for c in CASES])
def test_every_case_query_pair_executes(case):
    report = run_trials(
        case.reference_sql,
        case.candidate_sql,
        case.table_specs,
        n_trials=N_TRIALS,
        rows_per_trial=ROWS_PER_TRIAL,
        base_seed=SEED,
        edge_case_bias=BIAS,
    )
    assert report.n_trials == N_TRIALS


def test_true_mutants_are_eventually_caught_with_enough_bias_and_trials():
    mutants = [c for c in CASES if c.kind == "mutant"]
    assert mutants, "expected at least one labeled mutant in the corpus"
    for case in mutants:
        report = run_trials(
            case.reference_sql,
            case.candidate_sql,
            case.table_specs,
            n_trials=N_TRIALS,
            rows_per_trial=ROWS_PER_TRIAL,
            base_seed=SEED,
            edge_case_bias=BIAS,
        )
        assert report.n_differing > 0, (
            f"mutant {case.case_id} was never caught in {N_TRIALS} trials at bias={BIAS}; "
            f"hint: {case.edge_case_hint}"
        )


def test_unconditionally_safe_rewrites_are_never_falsely_flagged():
    safe = [c for c in CASES if c.kind == "safe_rewrite"]
    assert safe, "expected at least one safe rewrite in the corpus"
    for case in safe:
        report = run_trials(
            case.reference_sql,
            case.candidate_sql,
            case.table_specs,
            n_trials=N_TRIALS,
            rows_per_trial=ROWS_PER_TRIAL,
            base_seed=SEED,
            edge_case_bias=BIAS,
        )
        assert report.n_differing == 0, (
            f"safe rewrite {case.case_id} was falsely flagged as a behavior change"
        )


def test_conditional_rewrite_breaks_exactly_under_its_documented_condition():
    """q3_safe_rank_rewrite (RANK vs ROW_NUMBER) is equivalent on data with
    no exact-duplicate rows (bias 0.0) and can disagree once the generator
    injects an exact duplicate row (bias > 0), by construction of the
    generator's duplicate-injection step. This test pins that behavior so
    it cannot silently regress into either "always agrees" (meaning the
    duplicate-row injection broke) or "always disagrees" (meaning RANK and
    ROW_NUMBER diverge even without duplicates, which would indicate a
    bug in the oracle's comparison logic, not in the SQL)."""
    case = next(c for c in CASES if c.case_id == "q3_safe_rank_rewrite")

    report_no_bias = run_trials(
        case.reference_sql,
        case.candidate_sql,
        case.table_specs,
        n_trials=50,
        rows_per_trial=ROWS_PER_TRIAL,
        base_seed=SEED,
        edge_case_bias=0.0,
    )
    assert report_no_bias.n_differing == 0

    report_with_bias = run_trials(
        case.reference_sql,
        case.candidate_sql,
        case.table_specs,
        n_trials=50,
        rows_per_trial=ROWS_PER_TRIAL,
        base_seed=SEED,
        edge_case_bias=0.3,
    )
    assert report_with_bias.n_differing > 0
