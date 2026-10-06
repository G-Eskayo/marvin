# Swift Package Stack

## Lessons

### Per-run build folder
Swift Package Manager uses a shared `.build` folder by default. For CI runs, builds should be isolated using `--build-tests-path` to prevent collisions between parallel builds.

### macOS-only execution
Swift development requires macOS and Xcode. Builds must run on `macos-*` runners, not ubuntu. This has a higher cost on private repos (10x minutes vs. ubuntu).

### Test command
The standard test command is `swift test`, which is a SwiftPM convention. No detection needed if Package.swift exists.
