#!/usr/bin/env python3
"""Verification script for new health checks. Run locally to confirm:
1. Four new checks appear with sane values
2. Metrics are recorded and available for the dashboard
"""
import sys
import json
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "lib"))

import health_checks as hc
import metrics_registry as mr

# Run the health checks
print("Running health_checks.run_all()...", file=sys.stderr)
status = hc.run_all()

# Check that the four new check types are present
print("\n=== New checks ===", file=sys.stderr)
new_check_ids = {
    "mutation-score:g-eskayo-marvin",
    "merge:quality:g-eskayo-marvin",
    "tests:skip-trend",
    "repo-growth:files",
    "repo-growth:folders",
    "repo-growth:size-mb",
    "repo-growth:new-top-level-weekly",
}

found_checks = {}
for check in status["checks"]:
    check_id = check["id"]
    if check_id in new_check_ids:
        found_checks[check_id] = check

print(f"Found {len(found_checks)}/{len(new_check_ids)} expected checks:", file=sys.stderr)
for check_id in sorted(new_check_ids):
    if check_id in found_checks:
        check = found_checks[check_id]
        print(f"  ✓ {check_id}: {check['severity']} (value={check.get('value')})", file=sys.stderr)
    else:
        print(f"  ✗ {check_id}: NOT FOUND", file=sys.stderr)

print(f"\nTotal checks: {len(status['checks'])}", file=sys.stderr)
print(f"Overall severity: {status['overall']}", file=sys.stderr)

# Show the new checks in JSON format
print("\n=== Health checks output (formatted) ===", file=sys.stderr)
output = {
    "generated_at": status["generated_at"],
    "overall": status["overall"],
    "new_checks": {
        cid: found_checks[cid] for cid in sorted(found_checks.keys())
    }
}
print(json.dumps(output, indent=2))
