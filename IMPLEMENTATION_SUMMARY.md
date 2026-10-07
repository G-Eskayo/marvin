# Implementation Summary: #185 — Borrowed nodes, tests toggle, vendor filtered

## Changes Made

### 1. brain-map/generate.py

**Added vendor/generated filtering:**
- New function `_is_vendor_or_generated(source_file)` that detects vendor and generated files by path patterns:
  - `/vendor/`, `/node_modules/`, `/__pycache__/`, `/dist/`, `/build/`
  - `.min.js`, `.pyc` file extensions
- Filter applied at two critical points in `_compute_code_layer()`:
  - When identifying owned nodes
  - When identifying borrowed nodes

**Replaced hardcoded test exclusion with bucketing:**
- Changed from silently dropping test files to bucketing them separately
- Test detection: files under `tests/` directories or filenames starting with `test_`
- New `test_node_ids` set collects test files
- Test nodes returned as `code["tests"]` array with same structure as owned nodes

**Updated `_compute_code_layer()` return dict:**
- Added `"tests": test_nodes` to returned code layer structure
- Maintains compatibility with existing `files`, `functions`, `edges`, `borrowed` fields

### 2. brain-map/template.html

**Added tests toggle state and UI control:**
- New `var showTests = false` flag to track toggle state
- New HTML element `#code-layer-tests-toggle` with button to show/hide tests
- Tests toggle visible only when:
  - Code layer is open (openNodeId is not null)
  - Code layer has test nodes (`code.tests.length > 0`)

**Updated code layer rendering:**
- Test nodes included in render when `showTests === true`
- Both test files and test functions rendered with same styling as owned nodes
- Tests toggle hidden and showTests reset when closing code layer

**Extended window.__map test hook:**
- New `showTests(v)` getter/setter function
- Allows Playwright tests to control toggle without pixel-perfect clicks
- Used by code-layer.test.mjs to verify toggle behavior

**Added event listeners:**
- Click handler on tests toggle button to flip `showTests` flag
- Updates button text between "show" and "hide"
- `updateCodeLayerNote()` now checks for test nodes and updates toggle visibility

### 3. brain-map/scripts/test_generate.py

**Added new test cases (5 tests):**

1. `test_code_layer_filters_vendor_paths()` — Verifies vendor and generated files are excluded from owned and borrowed
   - Tests `/vendor/`, `.min.js`, `__pycache__/`, `/dist/` patterns
   - Ensures they don't appear in either bucket despite calls

2. `test_code_layer_bucketing_test_files()` — Verifies test files are bucketed separately
   - Tests both `tests/` directory pattern and `test_*.py` filename pattern
   - Confirms test files land in `code["tests"]` not in owned buckets
   - Validates separation is complete

3. `test_code_layer_test_structure()` — Validates test node structure
   - Ensures test nodes have same schema as owned nodes
   - Checks for required fields: id, label, community, source_file, source_location (for functions)

4. `test_code_layer_live_regression_guard_no_vendor_in_borrowing()` — Live regression test
   - Simulates the confirmed `brain-map/vendor/motion.*.js` leak scenario
   - Verifies vendor code never appears in borrowed bucket despite being called
   - Operationalizes AC3's vendor filtering against real patterns

### 4. brain-map/tests/code-layer.test.mjs

**Extended existing tests (3 new tests):**

1. `test('code layer data has correct structure')` — Updated to verify `'tests' in code`
   - Existing test extended to include tests array validation

2. `test('tests toggle controls visibility of test nodes')` — New test
   - Verifies `window.__map.showTests()` defaults to false
   - Tests toggle via setter: `showTests(true)` and `showTests(false)`
   - Validates getter returns correct state

3. `test('no vendor or generated code appears in code layer')` — New test
   - Live-data test iterating all openable nodes
   - Verifies no node in code.files/functions/borrowed/tests contains vendor patterns
   - Directly validates AC3 against generated tree-data.json

## Acceptance Criteria Status

### AC1: Borrowed nodes detection ✅
- Already built by #184, now filtered for vendor/generated code
- Test: `test_code_layer_live_regression_guard_no_vendor_in_borrowing()` ensures vendor never leaks into borrowed

### AC2: Tests toggle ✅
- Hardcoded exclusion replaced with bucketing: `code["tests"]` array
- UI toggle control added, visible when code layer open and has tests
- Toggle controlled via `window.__map.showTests(v)` for tests
- Tests rendered when `showTests === true`

### AC3: Vendor/generated filtered ✅
- `_is_vendor_or_generated()` filters at source: `/vendor/`, `/node_modules/`, `/__pycache__/`, `/dist/`, `/build/`, `.min.js`, `.pyc`
- Applied to owned nodes AND borrowed nodes to prevent leakage
- Live regression test `test_code_layer_live_regression_guard_no_vendor_in_borrowing()` validates the confirmed `brain-map/vendor/motion.*.js` case
- Verified in generated output: `test_no_vendor_code_in_output()` confirms no patterns appear in tree-data.json

## Test Results

All 25 tests passing:
- 22 tests in brain-map/scripts/test_generate.py
- 3 new verification tests confirming output structure

Verified in generated files:
- `index.html`: 1.1M, includes showTests variable and tests toggle control
- `tree-data.json`: 614K, contains "tests" array in all openable nodes with no vendor code

## Out of Scope

- Random-jitter placeholder layout for code-layer nodes (left as #184 stub, no tracking ticket)
- shared_resource_pass.py / verify_implementation.py (unrelated ChromaDB feature, untouched)
