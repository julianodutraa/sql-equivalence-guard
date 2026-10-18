"""A five-minute, reproducible walkthrough of the oracle on one query pair.

Run with: python examples/run_demo.py
Expected output is deterministic (fixed seed) and is reproduced verbatim
in README.md under "Quickstart".
"""

from __future__ import annotations

from sql_equivalence_guard.mutations import CASES
from sql_equivalence_guard.narrator import TemplateNarrator
from sql_equivalence_guard.oracle import run_trials

SEED = 20261018


def main() -> None:
    narrator = TemplateNarrator()
    case = next(c for c in CASES if c.case_id == "q2_inner_join")

    print(f"Case: {case.case_id}")
    print(f"Reference query:\n{case.reference_sql}")
    print(f"Candidate query (the 'refactor' under test):\n{case.candidate_sql}")
    print(f"What actually changed: {case.description}\n")

    report = run_trials(
        case.reference_sql,
        case.candidate_sql,
        case.table_specs,
        n_trials=30,
        rows_per_trial=40,
        base_seed=SEED,
        edge_case_bias=0.2,
    )

    print(f"Ran {report.n_trials} trials, {report.n_differing} found a difference "
          f"(kill rate {report.kill_rate:.1%}).")

    if report.first_difference is not None:
        narration = narrator.narrate(report.first_difference.diff_summary())
        print(f"\nRisk level: {narration.risk_level}")
        print(narration.text)


if __name__ == "__main__":
    main()
