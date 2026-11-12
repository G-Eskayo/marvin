1. [ ] `dashboard/electron/main/instance.js`: factor `readConfigFile()` out of `load()`, tracking `parseFailed`; use `instancePath()` consistently.
2. [ ] `dashboard/electron/main/instance.js`: `setFeature` re-reads fresh (bypassing cache) right before writing, refuses and throws when `parseFailed`, guards `config.features` to a plain object before assignment.
3. [ ] `dashboard/test/instance.test.js`: add the 12 `setFeature` cases above (write first, confirm they fail against the current code, then land step 1–2 to turn them green).
4. [ ] `dashboard/src/lib/addon_enable.js`: new pure `enableAddon(name, api)` helper.
5. [ ] `dashboard/test/addon_enable.test.js`: add the 4 cases above.
6. [ ] `dashboard/src/components/AddonNotSetUp.jsx`: accept and render an `error` prop (`role="alert"` pattern reused from `ProposalsSection.jsx`).
7. [ ] `dashboard/test/addon_not_set_up.test.jsx`: add the 4 cases above.
8. [ ] `dashboard/src/components/PortfolioHubGate.jsx`: add `error` state, wire `onEnable` through `enableAddon`, pass `error` to `AddonNotSetUp`.
9. [ ] Run the full dashboard test suite; run the app, trigger a corrupt `instance.json` and a valid-enable path by hand at 900px and 1440px, and pin screenshots on the PR per the acceptance criterion.
10. [ ] PR body: `Closes #786`, name the reused patterns (file + function) per the delegation preamble.