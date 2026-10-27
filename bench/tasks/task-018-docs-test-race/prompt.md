# Flaky dashboard CI: docs test deletes its folder while a background git status still writes .git

The dashboard tests for the Docs tab are flaky. The test deletes the temp folder while git status is still writing to .git in the background, causing race conditions.

Review the merged PR #655 and understand the root cause and fix applied. The issue involves synchronization between folder deletion and background git operations.
