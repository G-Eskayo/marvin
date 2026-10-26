#!/usr/bin/env python3
"""
spec_search.py — Generic spec-search loop for prompt optimization.

Repeatedly proposes edits to a prompt, scores against a frozen benchmark,
and accepts only edits that don't regress any sample. Terminates on:
- A bounded round count (MAX_ROUNDS)
- Two consecutive identical rejected edits (no progress)
- A no-op edit (proposal identical to current)
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Callable


@dataclass
class SpecSearchResult:
    """Result of a single search round."""
    round_num: int
    proposal: str
    accepted: bool
    before_scores: dict[str, float]
    after_scores: dict[str, float]
    regressions: list[str]
    accuracy_before: float
    accuracy_after: float
    cost_tokens: int = 0


class SpecSearchEngine:
    """Spec-search loop: iteratively propose edits, score, accept if no regression."""

    def __init__(
        self,
        initial_prompt: str,
        score_fn: Callable[[str, dict], dict[str, float]],
        teacher_fn: Callable[[str, float, list[str]], tuple[str, int]],
        max_rounds: int = 20,
    ):
        """
        initial_prompt: Starting prompt text
        score_fn: Maps (prompt, frozen_samples_dict) → {sample_id: score}
        teacher_fn: Maps (prompt, accuracy, regressions) → (proposal_text, tokens_spent)
        max_rounds: Max search iterations (default 20)
        """
        self.initial_prompt = initial_prompt
        self.score_fn = score_fn
        self.teacher_fn = teacher_fn
        self.max_rounds = max_rounds

    def run(self, frozen_samples: dict) -> tuple[str, list[SpecSearchResult]]:
        """Runs the search loop. Returns (final_prompt, history)."""
        if not frozen_samples:
            raise ValueError("frozen_samples is empty")

        history = []
        current_prompt = self.initial_prompt
        current_scores = self.score_fn(current_prompt, frozen_samples)

        if not current_scores:
            raise ValueError("score_fn returned no scores")

        last_rejected_proposal = None

        for round_num in range(1, self.max_rounds + 1):
            current_accuracy = sum(current_scores.values()) / len(current_scores)
            regressions = [sid for sid, score in current_scores.items() if score < 1.0]

            # Teacher proposes an edit
            try:
                proposal, tokens_spent = self.teacher_fn(
                    current_prompt,
                    current_accuracy,
                    regressions,
                )
            except Exception as e:
                raise RuntimeError(f"teacher_fn failed on round {round_num}: {e}")

            # Check termination conditions
            if proposal == current_prompt:
                # No-op: teacher proposed no change
                result = SpecSearchResult(
                    round_num=round_num,
                    proposal=proposal,
                    accepted=False,
                    before_scores=current_scores.copy(),
                    after_scores=current_scores.copy(),
                    regressions=regressions,
                    accuracy_before=current_accuracy,
                    accuracy_after=current_accuracy,
                    cost_tokens=tokens_spent,
                )
                history.append(result)
                break

            if proposal == last_rejected_proposal:
                # Repeated rejection: don't even score, just terminate
                result = SpecSearchResult(
                    round_num=round_num,
                    proposal=proposal,
                    accepted=False,
                    before_scores=current_scores.copy(),
                    after_scores=current_scores.copy(),
                    regressions=regressions,
                    accuracy_before=current_accuracy,
                    accuracy_after=current_accuracy,
                    cost_tokens=tokens_spent,
                )
                history.append(result)
                break

            # Score the proposal
            try:
                new_scores = self.score_fn(proposal, frozen_samples)
            except Exception as e:
                raise RuntimeError(f"score_fn failed on round {round_num}: {e}")

            new_accuracy = sum(new_scores.values()) / len(new_scores)
            regressions_this_round = [
                sid for sid in current_scores
                if new_scores.get(sid, 0.0) < current_scores.get(sid, 0.0)
            ]

            # Accept only if no regressions
            accepted = len(regressions_this_round) == 0

            result = SpecSearchResult(
                round_num=round_num,
                proposal=proposal,
                accepted=accepted,
                before_scores=current_scores.copy(),
                after_scores=new_scores.copy(),
                regressions=regressions_this_round,
                accuracy_before=current_accuracy,
                accuracy_after=new_accuracy if accepted else current_accuracy,
                cost_tokens=tokens_spent,
            )
            history.append(result)

            if accepted:
                current_prompt = proposal
                current_scores = new_scores
                last_rejected_proposal = None
            else:
                last_rejected_proposal = proposal

        return current_prompt, history
