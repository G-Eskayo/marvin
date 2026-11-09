<!-- marvin:decisions-addressed -->

The `golden-home` decision ("keep the image in `runs/golden/`") is already carried out — it was the shipped design before the decision was even recorded.

**Original commit** (commit `8d35f879`, "Box builds: a frozen marvin-build golden image, vm_run freeze and orphan sweep (#950)"): the golden image location at `runs/golden/` was established here and remains the current design.

**Changes since the decision** (2026-10-30): 
- `ticket/933-gate-box-runner` / `ticket/932-box-trial` stacked-branch merges 
- Single unrelated CI-fix commit `ca16c1aa` (flaky `simctl` mock in `lib/tests/test_cleanup_sweep.py`)

These changes do not touch the golden-home choice or any other PR #969 feature files. The `golden-home` design stands unchanged.

**Screenshots**: not applicable — this PR has no UI change (VM build scripts and `lib/vm_run.py` only), so no screenshots were taken or need retaking.
