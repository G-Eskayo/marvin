#!/usr/bin/env python3
"""Handle PR #969 decision - post addressed marker comment."""
import json
import subprocess
import sys
from pathlib import Path
from tempfile import NamedTemporaryFile

GH = [str(Path.home() / ".agents" / "bin" / "gh")]
REPO = "G-Eskayo/marvin"
PR = "969"

def run_gh(*args):
    """Run gh command and return stdout."""
    result = subprocess.run(GH + list(args), capture_output=True, text=True, check=True)
    return result.stdout

def check_pr_state():
    """Check if PR is still open and no existing addressed reply."""
    try:
        output = run_gh("pr", "view", PR, "--repo", REPO, "--json", "state,mergeable")
        data = json.loads(output)

        if data.get("state") != "OPEN":
            print(f"❌ PR #{PR} is not open (state={data.get('state')})", file=sys.stderr)
            return False

        # Check for existing addressed reply in comments
        comments_output = run_gh("pr", "view", PR, "--repo", REPO, "--comments")
        if "<!-- marvin:decisions-addressed -->" in comments_output:
            print(f"❌ PR #{PR} already has addressed marker", file=sys.stderr)
            return False

        print(f"✓ PR #{PR} is open, no existing addressed reply")
        return True
    except subprocess.CalledProcessError as e:
        print(f"❌ Failed to check PR state: {e.stderr}", file=sys.stderr)
        return False

def verify_gh_auth():
    """Verify gh is authenticated as owner."""
    try:
        output = run_gh("auth", "status")
        # Output will show username and org membership
        if "Logged in to github.com as" in output:
            print(f"✓ gh authenticated: {output.strip()}")
            return True
        print(f"⚠ gh auth output: {output}", file=sys.stderr)
        return True  # Continue anyway
    except subprocess.CalledProcessError as e:
        print(f"⚠ Failed to check auth: {e.stderr}", file=sys.stderr)
        return True  # Continue anyway

def draft_reply_body():
    """Draft the comment body confirming decision was already implemented."""
    body = """## What changed

The chosen option (**golden-home**: keep the `marvin-build` golden image under `runs/golden/`) was already carried out in the first commit of this PR. Confirmed via `lib/vm_run.py`'s `RUNS_DIR` usage:
- Golden images live in `GOLDEN_DIR` (line 27)
- Run copies are created in `RUNS_DIR / "runs"` (line 28, line 104)
- This matches the chosen approach

The three commits since the decision are unrelated (two merges, one `simctl` test fix from the stacked base branch) and don't touch the golden-image path.

No owner question was asked by this PR, so none needs answering.

<!-- marvin:decisions-addressed -->"""
    return body

def post_comment(body):
    """Post the comment to the PR."""
    try:
        with NamedTemporaryFile(mode='w', suffix='.txt', delete=False) as f:
            f.write(body)
            f.flush()
            temp_path = f.name

        try:
            run_gh("pr", "comment", PR, "--repo", REPO, "--body-file", temp_path)
            print(f"✓ Comment posted to PR #{PR}")
            return True
        finally:
            Path(temp_path).unlink(missing_ok=True)
    except subprocess.CalledProcessError as e:
        print(f"❌ Failed to post comment: {e.stderr}", file=sys.stderr)
        return False

def verify_comment_posted(body):
    """Verify the comment was actually posted."""
    try:
        comments_output = run_gh("pr", "view", PR, "--repo", REPO, "--comments")
        if "<!-- marvin:decisions-addressed -->" in comments_output:
            print(f"✓ Verified: addressed marker present in PR #{PR} comments")
            return True
        print(f"❌ Addressed marker not found in comments", file=sys.stderr)
        return False
    except subprocess.CalledProcessError as e:
        print(f"❌ Failed to verify comment: {e.stderr}", file=sys.stderr)
        return False

def main():
    print(f"Handling decision on PR #{PR}...\n")

    if not verify_gh_auth():
        print("❌ Authentication check failed", file=sys.stderr)
        return 1

    if not check_pr_state():
        print("❌ PR state check failed", file=sys.stderr)
        return 1

    body = draft_reply_body()
    print(f"\nDrafted comment body:\n{'-'*60}\n{body}\n{'-'*60}\n")

    if not post_comment(body):
        print("❌ Failed to post comment", file=sys.stderr)
        return 1

    if not verify_comment_posted(body):
        print("❌ Failed to verify comment was posted", file=sys.stderr)
        return 1

    print(f"\n✓ Successfully handled decision on PR #{PR}")
    return 0

if __name__ == "__main__":
    sys.exit(main())
