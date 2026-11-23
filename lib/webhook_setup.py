#!/usr/bin/env python3
"""
Manage GitHub webhook setup for MARVIN's boards and support repos.
Syncs the registered webhooks with what's configured in GitHub (repo settings).

Usage:
  webhook_setup.py existing               Show existing webhooks on board repos
  webhook_setup.py plan                   Show what would change
  webhook_setup.py sync                   Apply webhook changes (create/delete as needed)
"""

import sys
import os
import json
import subprocess
import argparse
from pathlib import Path


def _gh(*args, **kwargs):
    """Run gh CLI and return stdout."""
    result = subprocess.run(['gh'] + list(args), capture_output=True, text=True, **kwargs)
    if result.returncode != 0:
        raise RuntimeError(f"gh {' '.join(args)} failed: {result.stderr}")
    return result.stdout.strip()


def board_registry():
    """Read board repos from the registry (via Python module)."""
    # This mirrors lib/board_registry.py's _gh() subprocess pattern
    registry_py = Path(__file__).parent / 'board_registry.py'
    result = subprocess.run(
        ['python3', str(registry_py), 'list'],
        capture_output=True, text=True, cwd=str(Path(__file__).parent.parent)
    )
    if result.returncode != 0:
        return []
    try:
        return json.loads(result.stdout)
    except (json.JSONDecodeError, ValueError):
        return []


def support_repos():
    """Read support repos (via support_sync.py or similar)."""
    # Support repos are defined in support_sync.py; for now, return an empty list
    # (they can be added to the config file or discovered another way).
    return []


def existing_hooks(repo):
    """List existing webhooks on a GitHub repo."""
    try:
        output = _gh('webhook', 'list', repo, '--json', 'id,url,active,events')
        lines = output.strip().split('\n')
        hooks = []
        for line in lines:
            if line.strip().startswith('[') or line.strip().startswith('{'):
                try:
                    hooks.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
        return hooks
    except (RuntimeError, json.JSONDecodeError):
        return []


def plan_hook_changes(repos, webhook_url):
    """
    Plan what webhooks should exist on each repo.
    Returns { repo: { 'create': [...], 'delete': [...] } }
    """
    changes = {}
    for repo in repos:
        hooks = existing_hooks(repo)
        # Look for a webhook to our endpoint on this repo
        our_hook = next((h for h in hooks if webhook_url in h.get('url', '')), None)
        changes[repo] = {
            'create': [] if our_hook else [{'url': webhook_url, 'events': ['push', 'pull_request', 'issues']}],
            'delete': [h['id'] for h in hooks if h.get('url', '') and webhook_url not in h.get('url', '')]
        }
    return changes


def apply_hook_changes(changes):
    """Apply planned changes: create and delete webhooks."""
    for repo, plan in changes.items():
        for hook_def in plan.get('create', []):
            try:
                _gh('webhook', 'create', repo, '--url', hook_def['url'], '--events', ','.join(hook_def['events']))
                print(f"Created webhook on {repo}")
            except RuntimeError as e:
                print(f"Failed to create webhook on {repo}: {e}", file=sys.stderr)

        for hook_id in plan.get('delete', []):
            try:
                _gh('webhook', 'delete', repo, str(hook_id), '--confirm')
                print(f"Deleted webhook {hook_id} from {repo}")
            except RuntimeError as e:
                print(f"Failed to delete webhook {hook_id} from {repo}: {e}", file=sys.stderr)


def main():
    parser = argparse.ArgumentParser(description='Manage GitHub webhooks for MARVIN.')
    subparsers = parser.add_subparsers(dest='command', help='Subcommand')

    subparsers.add_argument('existing', nargs='?', help='Show existing webhooks')
    subparsers.add_argument('plan', nargs='?', help='Show planned changes')
    subparsers.add_argument('sync', nargs='?', help='Apply changes')

    args = parser.parse_args()

    # Get repos to manage
    repos = [b for b in board_registry() if b]
    repos.extend(support_repos())

    if not repos:
        print("No repos found in registry", file=sys.stderr)
        sys.exit(1)

    # Webhook URL (would come from environment or config in production)
    webhook_url = os.environ.get('MARVIN_WEBHOOK_URL', 'https://your-domain.com/gh-webhook')

    if args.command == 'existing':
        for repo in repos:
            hooks = existing_hooks(repo)
            print(f"{repo}: {len(hooks)} webhooks")
            for h in hooks:
                print(f"  {h.get('id')}: {h.get('url')} ({','.join(h.get('events', []))})")

    elif args.command == 'plan':
        changes = plan_hook_changes(repos, webhook_url)
        for repo, plan in changes.items():
            if plan['create'] or plan['delete']:
                print(f"{repo}:")
                for hook in plan['create']:
                    print(f"  + {hook['url']}")
                for hook_id in plan['delete']:
                    print(f"  - {hook_id}")

    elif args.command == 'sync':
        changes = plan_hook_changes(repos, webhook_url)
        apply_hook_changes(changes)
        print("Webhook setup complete")

    else:
        parser.print_help()


if __name__ == '__main__':
    main()
