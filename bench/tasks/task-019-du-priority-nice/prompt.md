# Main is falsely red: the du priority test fails whenever the suite itself runs niced

The test suite is set to run with "nice" priority, but the du priority test (which measures disk usage) fails when the whole suite is niced.

Review the merged PR #654 and understand why the du test is sensitive to process priority and how the fix addresses this issue. The root cause involves how process priority affects system calls or measurements.
