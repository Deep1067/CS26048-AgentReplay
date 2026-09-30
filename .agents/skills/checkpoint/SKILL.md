---
name: checkpoint
description: >-
  Use this skill when the user runs the /checkpoint slash command to summarize changes, explain them, generate viva questions, and commit.
---

# Checkpoint Workflow

When triggered via the `/checkpoint` command, follow these steps:

1. **Summarize Changes**: Review the `git diff` or recent uncommitted changes.
2. **Explain in 5 Lines**: Provide a concise 5-line explanation of what was changed and why.
3. **Viva Questions**: Generate 3 "viva" (interview/review) questions for the user based on the recent changes to test their understanding or prompt design review.
4. **Commit**: Automatically execute `git add .` and `git commit -m "<clear_message>"` with a descriptive and clear commit message based on the changes.
