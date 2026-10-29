"""pr-shots: put screenshots in a PR the one way that keeps working (marvin #735).

    pr-shots [--pr N] [--body-file F] image.png[::what to look at] ...

Run it in the PR's worktree. It copies the images into the repo (docs/images/pr/<branch>/), commits and pushes them,
links each by its full commit SHA on raw.githubusercontent.com (shows for private repos in the dashboard and never turns
into a newer picture), checks every link answers 200, and writes the section into the PR body between
<!-- marvin:shots --> markers, replacing the last one. Run it again after a look change: that's the re-pin.

With no PR yet it writes the section into --body-file (or prints it), for `gh pr create --body-file`.
The engine repo keeps images out of its own tree (ADR 0071): they go to the private instance repo instead.
"""
from __future__ import annotations
import argparse
import os
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import instance  # noqa: E402
import pr_images  # noqa: E402

GH = os.environ.get("MARVIN_PR_SHOTS_GH") or str(Path.home() / ".agents" / "bin" / "gh")
TRAILER = "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"


def git(cwd, *args, check=True) -> str:
    p = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True)
    if check and p.returncode != 0:
        raise SystemExit(f"pr-shots: git {' '.join(args)} failed: {(p.stderr or p.stdout).strip()[-300:]}")
    return p.stdout.strip()


def repo_of(cwd) -> str:
    url = git(cwd, "remote", "get-url", "origin")
    m = re.search(r"github\.com[:/]([^/]+/[^/.]+?)(?:\.git)?$", url)
    if not m:
        raise SystemExit(f"pr-shots: origin isn't a GitHub repo ({url})")
    return m.group(1)


def slug(branch: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "-", branch).strip("-") or "pr"


def parse_image(arg: str) -> tuple[Path, str]:
    path, _, caption = arg.partition("::")
    return Path(path).expanduser(), caption.strip()


def section(links: list[tuple[str, str, str]]) -> str:
    """The screenshots section: a line on what to look at, then the image, for each."""
    out = ["## Screenshots", ""]
    for name, caption, url in links:
        if caption:
            out.append(caption)
            out.append("")
        out.append(f"![{caption or name}]({url})")
        out.append("")
    return "\n".join(out).strip()


def verify(urls, token: str | None, opener=urllib.request.urlopen) -> list[str]:
    """The links that don't answer 200 (private repos need the token)."""
    bad = []
    for u in urls:
        req = urllib.request.Request(u, method="HEAD", headers={"Authorization": f"token {token}"} if token else {})
        try:
            with opener(req, timeout=20) as r:
                if r.status != 200:
                    bad.append(f"{u} ({r.status})")
        except urllib.error.HTTPError as e:
            bad.append(f"{u} ({e.code})")
        except Exception as e:  # noqa: BLE001
            bad.append(f"{u} ({e})")
    return bad


def gh(*args, check=True) -> subprocess.CompletedProcess:
    p = subprocess.run([GH, *args], capture_output=True, text=True)
    if check and p.returncode != 0:
        raise SystemExit(f"pr-shots: gh {' '.join(args[:3])} failed: {(p.stderr or p.stdout).strip()[-300:]}")
    return p


def store(images, cwd: Path, repo: str, branch: str) -> tuple[str, Path, list[Path]]:
    """Commit and push the images. Returns (repo the links point at, its checkout, paths inside it)."""
    if repo == instance.engine_repo():
        home = instance.instance_dir()
        target_repo, root, rel_dir = repo_of(home), home, Path("docs/screenshots") / slug(branch)
        push_branch = git(home, "rev-parse", "--abbrev-ref", "HEAD")
    else:
        target_repo, root, rel_dir = repo, cwd, Path("docs/images/pr") / slug(branch)
        push_branch = branch
    (root / rel_dir).mkdir(parents=True, exist_ok=True)
    rels = []
    for src, _ in images:
        rel = rel_dir / src.name
        if src.resolve() != (root / rel).resolve():
            shutil.copy2(src, root / rel)
        rels.append(rel)
    git(root, "add", "--", *map(str, rels))
    if git(root, "diff", "--cached", "--name-only", "--", *map(str, rels)):
        git(root, "commit", "-q", "-m", f"Screenshots for {branch}", "-m", TRAILER, "--", *map(str, rels))
    git(root, "push", "-q", "origin", f"HEAD:refs/heads/{push_branch}")
    return target_repo, root, rels


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="pr-shots", description=__doc__.split("\n\n")[1])
    ap.add_argument("images", nargs="+", help="image files, each optionally followed by ::what to look at")
    ap.add_argument("--pr", help="PR number or URL (default: the PR for this branch)")
    ap.add_argument("--body-file", help="with no PR yet: write the section into this body file")
    ap.add_argument("--no-verify", action="store_true", help=argparse.SUPPRESS)
    a = ap.parse_args(argv)

    cwd = Path(git(Path.cwd(), "rev-parse", "--show-toplevel"))
    repo = repo_of(cwd)
    branch = git(cwd, "rev-parse", "--abbrev-ref", "HEAD")
    images = [parse_image(i) for i in a.images]
    missing = [str(p) for p, _ in images if not p.is_file()]
    if missing:
        raise SystemExit(f"pr-shots: no such image: {', '.join(missing)}")

    target_repo, root, rels = store(images, cwd, repo, branch)
    sha = git(root, "rev-parse", "HEAD")
    links = [(p.name, cap, f"https://raw.githubusercontent.com/{target_repo}/{sha}/{rel}") for (p, cap), rel in zip(images, rels)]
    if not a.no_verify:
        token = gh("auth", "token", check=False).stdout.strip() or None
        bad = verify([u for _, _, u in links], token)
        if bad:
            raise SystemExit("pr-shots: these links don't show yet: " + "; ".join(bad))
    text = section(links)

    pr = a.pr or (gh("pr", "view", "--repo", repo, branch, "--json", "number", "-q", ".number", check=False).stdout.strip())
    if pr:
        body = gh("pr", "view", pr, "--repo", repo, "--json", "body", "-q", ".body").stdout
        with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False) as f:
            f.write(pr_images.with_shots_section(body, text))
        gh("pr", "edit", pr, "--repo", repo, "--body-file", f.name)
        os.unlink(f.name)
        print(f"pr-shots: {len(links)} image(s) pinned to {sha[:7]} in PR {pr}")
    elif a.body_file:
        p = Path(a.body_file)
        p.write_text(pr_images.with_shots_section(p.read_text() if p.exists() else "", text))
        print(f"pr-shots: {len(links)} image(s) pinned to {sha[:7]}; section written into {p}")
    else:
        print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
