#!/usr/bin/env python3
"""
readiness.py — Project readiness assessment from onboarding plans.

Pure function: walk an onboarding plan's pieces, collect missing/needs-human items,
return {ready: bool, gaps: [plain-word phrases]}. No plan → not ready with "not onboarded yet".
"""
from __future__ import annotations


PIECE_LABELS = {
    "profile": "a project profile",
    "stack": "stack info",
    "test_command": "a test command",
    "ci": "CI",
    "triage_labels": "triage labels",
    "agent_docs": "agent docs",
    "board": "a project board",
    "clone_and_toolchain": "clone and toolchain setup",
    "generated_paths": "generated paths",
    "baseline": "a baseline",
}


def project_readiness(plan: dict | None) -> dict:
    """Return {ready: bool, gaps: [plain phrases]}.

    plan: onboarding plan dict with structure {pieces: {piece_key: {state, reason}, ...}, ...}
    No plan → not ready with "not onboarded yet".
    piece.state: "missing" or "needs-human" counts as a gap.
    """
    if plan is None:
        return {"ready": False, "gaps": ["not onboarded yet"]}

    pieces_dict = plan.get("pieces") or {}
    gaps = []

    for key, piece_info in pieces_dict.items():
        if isinstance(piece_info, dict):
            state = piece_info.get("state")
        else:
            continue
        if state in ("missing", "needs-human"):
            label = PIECE_LABELS.get(key, key.replace("_", " "))
            gaps.append(label)

    return {"ready": len(gaps) == 0, "gaps": gaps}
