---
name: rhoai-release-ui
description: Launch the FastAPI web UI for RHOAI release onboarding with real-time progress tracking and streaming logs
allowed-tools: Bash
user-invocable: true
---

# RHOAI Release UI

Launches a FastAPI web interface for RHOAI release onboarding automation with:
- Interactive web form for version inputs
- Real-time streaming logs with ANSI color support
- Progress tracking across all 3 pipeline steps
- PR/MR URL extraction and display
- Job cancellation support
- Multi-job management (in-memory state)

## Prerequisites

- `uv` must be installed and in PATH
  - Install: `curl -LsSf https://astral.sh/uv/install.sh | sh`
- Port 8000 must be available
- Environment variables (same as the CLI):
  - `GITHUB_TOKEN` — for RBC Release and RBC Main steps
  - `KONFLUX_REPO_TOKEN` — for Konflux step
  - Optional: other RBC_* and KONFLUX_* configuration variables

## Usage

```
/rhoai-release-ui
```

The UI will be accessible at: http://localhost:8000

## Implementation

SKILL_DIR is the absolute path of the directory containing this SKILL.md.

---

## Step 1: Launch the web UI

Execute the FastAPI server with uvicorn:

```bash
cd "$SKILL_DIR"

echo "Starting RHOAI Release Onboarding Web UI..."
echo ""
echo "The UI will be available at: http://localhost:8000"
echo ""
echo "To stop the server, press Ctrl+C"
echo ""

uv run --script web_ui.py
```

This will:
- Start the FastAPI server on http://0.0.0.0:8000
- Serve the interactive HTML UI
- Provide REST API endpoints for job management

---

## Step 2: Usage instructions

**Print after launch:**

```
╔══════════════════════════════════════════════════════════════╗
║     RHOAI RELEASE ONBOARDING WEB UI - RUNNING                ║
╚══════════════════════════════════════════════════════════════╝

Web UI: http://localhost:8000

Features:
  • Interactive form for version inputs
  • Real-time streaming logs with color support
  • Automatic PR/MR URL extraction
  • Enable/disable individual pipeline steps
  • Job cancellation support

API Endpoints:
  POST   /run          - Start a new pipeline run
  GET    /stream/{id}  - Server-sent events for job logs
  POST   /cancel/{id}  - Cancel a running job
  GET    /status/{id}  - Get job status
  GET    /jobs         - List all jobs

Press Ctrl+C to stop the server.
═══════════════════════════════════════════════════════════════
```

---

## Features

### Frontend (index.html)
- Bootstrap-based responsive UI
- ANSI color code rendering for terminal output
- Auto-scrolling logs
- Progress indicators for each step
- Collapsible step sections
- Dark/light theme support

### Backend (web_ui.py)
- FastAPI async framework
- Server-sent events (SSE) for real-time log streaming
- Subprocess management with cancellation
- In-memory job state storage
- Automatic PR/MR URL extraction from logs
- Step status tracking (pending/running/success/failed/cancelled/skipped)

### Supported Operations
1. **Run Pipeline** - Execute all 3 steps sequentially
2. **Enable/Disable Steps** - Selectively run specific steps
3. **Dry-Run Mode** - Preview changes without committing
4. **Cancel Jobs** - Stop running pipeline jobs
5. **Multi-Job Support** - Track multiple concurrent releases

---

## Error Reference

| Error | Where | Action |
|-------|-------|--------|
| Port 8000 in use | Step 1 | Stop other service or change port in web_ui.py |
| `uv` not installed | Step 1 | `curl -LsSf https://astral.sh/uv/install.sh \| sh` |
| Template not found | Step 1 | Ensure templates/index.html exists in skill directory |
| Job execution fails | Runtime | Check GITHUB_TOKEN and KONFLUX_REPO_TOKEN are set |
| Browser can't connect | Step 1 | Check firewall, ensure server started successfully |

---

## Notes

- The server runs in the foreground; use Ctrl+C to stop
- Job state is in-memory only; restarting the server clears all jobs
- Multiple users can access the UI simultaneously
- Each job gets a unique UUID for tracking
- PR/MR URLs are auto-extracted from subprocess output
- The UI auto-refreshes job list every 5 seconds
