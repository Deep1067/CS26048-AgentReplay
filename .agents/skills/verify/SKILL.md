---
name: verify
description: >-
  Use this skill when the user runs the /verify slash command to run ruff and pytest, fix failures, and report results.
---

# Verify Workflow

When triggered via the `/verify` command, follow these steps:

1. **Run Linter**: Execute `ruff check .` in the terminal.
2. **Run Tests**: Execute `pytest` in the terminal.
3. **Fix Failures**: If either ruff or pytest reports errors or failures, analyze the output and make necessary code edits to fix them.
4. **Report Results**: Once everything passes, generate a summary report of what was checked and any fixes that were applied.
