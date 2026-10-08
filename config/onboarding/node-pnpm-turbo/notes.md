# Node + pnpm + Turbo Stack

This stack detects monorepos using pnpm and Turbo for workspace management.

## Key differences from node-electron

- **Workspace config**: Projects have `pnpm-workspace.yaml` (or `turbo.json` as an alternative marker) at the root, signaling a monorepo structure.
- **Package manager**: Uses `pnpm` instead of `npm` or `yarn`.
- **Lockfile**: `pnpm-lock.yaml` replaces `package-lock.json`.
- **Cache directory**: `.turbo/` holds Turbo's build cache (safe to regenerate).

## pnpm version pinning (corepack)

The CI workflow uses `corepack enable` before `actions/setup-node`. This reads the `packageManager` field in the root `package.json`:

```json
{
  "packageManager": "pnpm@9.0.0"
}
```

**Do not install pnpm separately.** Corepack will fail if you install a different version; let it manage the version from package.json.

## Test script

The root `package.json` should have a `test` script that delegates to workspace packages:

```json
{
  "scripts": {
    "test": "turbo run test"
  }
}
```

Each workspace package defines its own `test` script; `turbo run test` runs them in dependency order. **Never guess a test command** (ADR 0005); if a root test script is missing, the onboarding plan will ask for human confirmation.

## Generated paths

- `node_modules/`: pnpm's dependency cache (can be regenerated from lockfile).
- `pnpm-lock.yaml`: The lock file (commit it).
- `.turbo/`: Turbo's task cache (safe to regenerate).

These are listed in the onboarding profile's `generated_candidates` and will appear in the readiness plan for confirmation.
