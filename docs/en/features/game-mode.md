---
title: Game Mode
---

# Game Mode

Interactive game tasks where agents play text-adventure games via HTTP API instead of submitting code.

## How It Works

- Task marked with `"game_mode": true` in JSON
- Judge image contains the game server
- Agent interacts via HTTP game endpoints
- Multiple sessions allowed (explore different strategies)
- Scoring from the game's own score (no test suite)

## Game API

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/api/v1/game/{run_id}/{task_id}/new` | Start a new session |
| `POST` | `/api/v1/game/{run_id}/{task_id}/{sid}/step` | Take an action |
| `GET` | `/api/v1/game/{run_id}/{task_id}/{sid}/status` | Check session status |
| `POST` | `/api/v1/game/{run_id}/{task_id}/{sid}/close` | End a session |

## Response Format

```json
{
  "session_id": "...",
  "observation": "You are in a dark room...",
  "score": 10,
  "peak_score": 15,
  "max_score": 350,
  "done": false,
  "moves": 5
}
```

## Available Game Tasks

| Task | Genre |
|------|-------|
| Jericho Anchorhead | Text adventure |
| Jericho Trinity | Text adventure |
| Jericho Tryst of Fate | Text adventure (draft) |

## Session Management

- Sessions auto-close after **10 minutes** idle
- Max **200** concurrent sessions
- Close all sessions for a run:

```
POST /api/v1/game/{run_id}/{task_id}/close-all
```
