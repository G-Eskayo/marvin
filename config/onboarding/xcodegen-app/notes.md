# Xcode App Stack

## Lessons

### Per-run build folder
Xcode app builds use a shared DerivedData folder by default. For CI runs and parallel builds, use a per-build temp folder via the profile's `"build_folder"` command to prevent database locking conflicts.

### macOS-only execution
Xcode app development requires macOS and full Xcode. Builds must run on `macos-*` runners, not ubuntu. This has a higher cost on private repos (10x minutes vs. ubuntu).

### Project generation
Projects built with xcodegen require running `xcodegen generate` before building. The generated `.xcodeproj` is typically not tracked in git.

### Cost implications
Public repos are eligible for free macOS runners. Private repos incur significant CI costs (10x per minute). Confirm before enabling CI for a private xcodegen app.
