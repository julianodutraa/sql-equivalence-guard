"""Command-line entry point: run the full mutant corpus and print a report.

Usage:
    python -m sql_equivalence_guard.cli --trials 200 --rows 60 --bias 0.0
    python -m sql_equivalence_guard.cli --trials 200 --rows 60 --bias 0.35
"""

from __future__ import annotations

import argparse
import json

from sql_equivalence_guard.mutations import CASES
from sql_equivalence_guard.narrator import TemplateNarrator
from sql_equivalence_guard.oracle import run_trials


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the SQL equivalence oracle over the mutant corpus.")
    parser.add_argument("--trials", type=int, default=200)
    parser.add_argument("--rows", type=int, default=60)
    parser.add_argument("--bias", type=float, default=0.0, help="edge-case bias in [0, 1]")
    parser.add_argument("--seed", type=int, default=20261018)
    parser.add_argument("--json", action="store_true", help="emit machine-readable JSON instead of a table")
    args = parser.parse_args()

    narrator = TemplateNarrator()
    rows = []
    for case in CASES:
        report = run_trials(
            case.reference_sql,
            case.candidate_sql,
            case.table_specs,
            n_trials=args.trials,
            rows_per_trial=args.rows,
            base_seed=args.seed,
            edge_case_bias=args.bias,
        )
        narration = None
        if report.first_difference is not None:
            narration = narrator.narrate(report.first_difference.diff_summary())

        rows.append(
            {
                "case_id": case.case_id,
                "kind": case.kind,
                "description": case.description,
                "kill_rate": report.kill_rate,
                "n_trials": report.n_trials,
                "n_differing": report.n_differing,
                "narration": narration.text if narration else None,
                "risk_level": narration.risk_level if narration else "SAFE",
            }
        )

    if args.json:
        print(json.dumps({"bias": args.bias, "trials": args.trials, "rows_per_trial": args.rows, "cases": rows}, indent=2, default=str))
        return

    print(f"{'case_id':30} {'kind':14} {'kill_rate':>10} {'risk_level'}")
    for row in rows:
        print(f"{row['case_id']:30} {row['kind']:14} {row['kill_rate']:>10.2%} {row['risk_level']}")


if __name__ == "__main__":
    main()
