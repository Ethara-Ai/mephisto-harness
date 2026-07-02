---
title: Visualizer
---

# Visualizer

Web-based UI for browsing run results.

## Usage

```bash
sforge visualizer --runs-dir logs/runs --port 8000
```

## Pages

| Page | Path | Description |
|------|------|-------------|
| Leaderboard | `/` | Best run per task, sortable |
| Task View | `/task/{task_id}` | All runs for a specific task |
| Run Detail | `/run/{run_id}/{task_id}` | Submission history with pass rate chart |
| Submission Detail | `/run/{run_id}/{task_id}/submission/{n}` | Per-test results, raw output |

## Features

- Supports all submission types: agent, auto-eval, game
- Real-time test result viewing
- Raw test output access
- Score and pass rate tracking across submissions
