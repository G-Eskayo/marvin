# Mac app screenshots (marvin #727)

How a Mac app gets images into its PRs without anyone clicking it.

1. Copy `MarvinScreenshot.swift` into the app, unchanged.
2. Before the app starts anything with side effects (microphone, hotkeys, network), call
   `MarvinScreenshot.runIfRequested { … }` with the view for the scene its launch arguments name.
   Every screen worth reviewing, including menus, panels and pills that only appear on a key press, gets its own
   launch argument (e.g. `-MarvinScene menu`).
3. In the project profile, add the scenes:

```json
"evidence": {
  "ui_paths": ["App/Sources/**"],
  "dev": {"macos_app": {
    "project_dir": "App", "prepare": [["xcodegen", "generate"]],
    "project": "MarvinVoice.xcodeproj", "scheme": "MarvinVoice",
    "scenes": [{"name": "menu", "args": ["-MarvinScene", "menu"]}]
  }}
}
```

A SwiftPM app uses `"swiftpm_product": "<product>"` instead of `project` + `scheme`.

The pipeline runs each scene in light and dark with `-MarvinScreenshot <png> -MarvinAppearance light|dark`, checks a
real PNG came back, and puts the images in the PR. The app draws itself, so no Screen Recording permission is needed.
Limits: it's a drawing of the view, not a capture of the screen, so desktop blur behind translucent materials and the
menu bar itself don't appear.
