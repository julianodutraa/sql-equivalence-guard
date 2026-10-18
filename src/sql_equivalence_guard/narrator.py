"""Turn an oracle diff into a plain-English risk narration.

Two narrators are provided:

``TemplateNarrator``
    Deterministic, offline, no API key required. This is what the test
    suite and the CLI use by default, and it is the only narrator this
    project can honestly claim is "evaluated" in an automated,
    reproducible sense: its output is a pure function of the diff
    statistics, so the same diff always produces the same narration and
    the same risk label.

``LLMNarrator``
    A thin, optional wrapper around an Anthropic-compatible chat
    completion call. It is not exercised by the automated test suite
    (there is no API key baked into a public repository, nor should
    there be), and it is not what generated the honest metrics in
    ``eval/``. ``eval/narrator_review.json`` documents, with provenance,
    a separate manual evaluation: a held-out sample of diffs was
    narrated by Claude (Sonnet 5) acting as the LLM, and those
    narrations were scored against the same faithfulness rubric
    ``TemplateNarrator`` is held to. That evaluation is honest about
    where the free-form narrator did *worse* than the deterministic
    one, specifically by overclaiming causal certainty on a diff where
    only correlation with the known mutation was observable.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Protocol

RiskLevel = str  # "SAFE" | "LIKELY_SAFE" | "BEHAVIOR_CHANGE"


@dataclass(frozen=True)
class Narration:
    risk_level: RiskLevel
    text: str


class Narrator(Protocol):
    def narrate(self, diff_summary: dict) -> Narration: ...


class TemplateNarrator:
    """Deterministic, template-based narration of an oracle diff."""

    def narrate(self, diff_summary: dict) -> Narration:
        if diff_summary["equivalent"]:
            return Narration(
                risk_level="SAFE",
                text=(
                    f"No difference was observed across the trials run so far "
                    f"({diff_summary['n_rows_a']} rows on both sides of the most recent "
                    f"trial, seed {diff_summary['seed']}). This is evidence of equivalence "
                    f"on the data distributions exercised, not a proof: a mutation that "
                    f"only manifests on data the generator rarely produces would look "
                    f"identical to a true safe rewrite until the generator is biased "
                    f"toward that specific pattern."
                ),
            )

        total_a = diff_summary["total_rows_only_in_a"]
        total_b = diff_summary["total_rows_only_in_b"]
        cols = ", ".join(diff_summary["columns"]) or "unknown"

        if total_a and total_b:
            shape = (
                f"{total_a} row(s) appear only in the reference query and "
                f"{total_b} row(s) appear only in the candidate query"
            )
        elif total_a:
            shape = f"{total_a} row(s) present in the reference query are missing from the candidate query"
        else:
            shape = f"{total_b} row(s) appear in the candidate query that are absent from the reference query"

        text = (
            f"A difference was found on seed {diff_summary['seed']}: {shape}, "
            f"over columns [{cols}]. Row counts were {diff_summary['n_rows_a']} "
            f"(reference) vs {diff_summary['n_rows_b']} (candidate). This is a "
            f"concrete, reproducible counterexample (rerun with the same seed to "
            f"confirm), not a statistical inference, so no confidence interval is "
            f"attached to it; the confidence interval belongs to the *absence* of "
            f"such counterexamples across many trials, reported separately."
        )
        return Narration(risk_level="BEHAVIOR_CHANGE", text=text)


class LLMNarrator:
    """Optional LLM-backed narrator. Not used by the automated test suite.

    Requires ``ANTHROPIC_API_KEY`` (or ``OPENAI_API_KEY`` for the OpenAI
    fallback) to be set; raises at call time otherwise, rather than at
    import time, so importing this module never requires network access
    or a key.
    """

    def __init__(self, model: str = "claude-sonnet-5"):
        self.model = model

    def build_prompt(self, diff_summary: dict) -> str:
        return (
            "You are reviewing the output of a SQL differential-testing oracle. "
            "Given the diff summary below, classify the risk as SAFE, LIKELY_SAFE, "
            "or BEHAVIOR_CHANGE, and explain in two sentences what evidence supports "
            "that classification. Do not claim a root cause unless the diff itself "
            "identifies the SQL change that caused it; state only what the data shows.\n\n"
            f"Diff summary (JSON): {diff_summary}"
        )

    def narrate(self, diff_summary: dict) -> Narration:
        if not (os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("OPENAI_API_KEY")):
            raise RuntimeError(
                "LLMNarrator requires ANTHROPIC_API_KEY or OPENAI_API_KEY to be set. "
                "Use TemplateNarrator for offline/CI use; see narrator.py module docstring."
            )
        raise NotImplementedError(
            "Network call intentionally not implemented in this public repository. "
            "build_prompt() above is the exact prompt that would be sent; wire in "
            "your preferred Anthropic/OpenAI client here."
        )
