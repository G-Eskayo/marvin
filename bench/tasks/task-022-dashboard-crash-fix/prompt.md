# Signed dashboard builds stop crashing: electron-builder never publishes (#540)

The signed dashboard builds were crashing because electron-builder's publish step was failing. The issue is that electron-builder never actually publishes in certain conditions.

Review the merged PR #541 and understand why electron-builder was failing to publish and how the fix prevents the crash. The solution likely involves handling null/missing values properly or conditionally skipping the publish step.
