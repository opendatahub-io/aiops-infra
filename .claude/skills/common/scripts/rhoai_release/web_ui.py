"""FastAPI web UI for RHOAI Release Onboarding automation.

Start with:
    uvicorn src.web_ui:app --host 0.0.0.0 --port 8080
or:
    python run_ui.py

Then open http://localhost:8080 in your browser.
"""

import asyncio
import json
import os
import re
import sys
import uuid
from pathlib import Path
from typing import Dict, List, Optional

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, StreamingResponse
from pydantic import BaseModel

load_dotenv()

app = FastAPI(title="RHOAI Release Onboarding")

REPO_ROOT = Path(__file__).resolve().parent.parent
TEMPLATES = REPO_ROOT / "templates"
PYTHON = sys.executable

# In-memory store: job_id -> job state / async queue / cancellation
_jobs: Dict[str, dict] = {}
_queues: Dict[str, asyncio.Queue] = {}
_cancel_events: Dict[str, asyncio.Event] = {}
_active_procs: Dict[str, asyncio.subprocess.Process] = {}


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------

class RunRequest(BaseModel):
    previous_version: str
    new_version: str
    dry_run: bool = False
    repo_dir: str = "konflux-release-data"
    enabled_steps: List[bool] = [True, True, True]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _new_step(name: str, description: str) -> dict:
    return {
        "name": name,
        "description": description,
        "status": "pending",   # pending | running | success | failed | skipped
        "logs": [],
        "pr_url": None,
        "mr_url": None,
        "returncode": None,
    }


def _extract_links(text: str) -> dict:
    """Extract GitHub PR and GitLab MR URLs from a line of output."""
    result: dict = {}
    gh = re.search(r"https://github\.com/[\w.\-/]+/pull/\d+", text)
    if gh:
        result["pr_url"] = gh.group()
    gl = re.search(r"https://gitlab\.[^\s]+/-/merge_requests/\d+", text)
    if gl:
        result["mr_url"] = gl.group()
    return result


# ---------------------------------------------------------------------------
# Pipeline execution
# ---------------------------------------------------------------------------

async def _run_step(
    job_id: str,
    step_idx: int,
    cmd: list,
    queue: asyncio.Queue,
) -> bool:
    """Run one script step, stream output to the SSE queue. Returns True on success."""
    step = _jobs[job_id]["steps"][step_idx]
    cancel = _cancel_events.get(job_id)

    if cancel and cancel.is_set():
        step["status"] = "cancelled"
        await queue.put(json.dumps({"type": "step_end", "step": step_idx, "status": "cancelled"}))
        return False

    step["status"] = "running"
    await queue.put(json.dumps({"type": "step_start", "step": step_idx}))

    env = {**os.environ}

    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            cwd=REPO_ROOT,
            env=env,
        )
    except Exception as exc:
        msg = f"[ERROR] Failed to launch process: {exc}"
        step["logs"].append(msg)
        step["status"] = "failed"
        await queue.put(json.dumps({"type": "log", "step": step_idx, "line": msg}))
        await queue.put(json.dumps({"type": "step_end", "step": step_idx, "status": "failed"}))
        return False

    _active_procs[job_id] = proc
    assert proc.stdout is not None  # always set when PIPE

    async for raw in proc.stdout:
        line = raw.decode("utf-8", errors="replace").rstrip()
        step["logs"].append(line)
        links = _extract_links(line)
        if links.get("pr_url") and not step.get("pr_url"):
            step["pr_url"] = links["pr_url"]
            _jobs[job_id]["pr_url"] = links["pr_url"]
        if links.get("mr_url") and not step.get("mr_url"):
            step["mr_url"] = links["mr_url"]
            _jobs[job_id]["mr_url"] = links["mr_url"]
        payload = {"type": "log", "step": step_idx, "line": line}
        payload.update(links)
        await queue.put(json.dumps(payload))

    await proc.wait()
    _active_procs.pop(job_id, None)

    was_cancelled = cancel and cancel.is_set()
    if was_cancelled:
        step["status"] = "cancelled"
        step["returncode"] = proc.returncode
        msg = "[INFO] Step cancelled by user."
        step["logs"].append(msg)
        await queue.put(json.dumps({"type": "log", "step": step_idx, "line": msg}))
        await queue.put(json.dumps({
            "type": "step_end", "step": step_idx, "status": "cancelled",
            "pr_url": step.get("pr_url"), "mr_url": step.get("mr_url"),
        }))
        return False

    success = proc.returncode == 0
    step["status"] = "success" if success else "failed"
    step["returncode"] = proc.returncode
    await queue.put(
        json.dumps(
            {
                "type": "step_end",
                "step": step_idx,
                "status": step["status"],
                "pr_url": step.get("pr_url"),
                "mr_url": step.get("mr_url"),
            }
        )
    )
    return success


async def _run_pipeline(job_id: str, req: RunRequest) -> None:
    """Run all three automation scripts sequentially."""
    queue = _queues[job_id]
    _jobs[job_id]["status"] = "running"

    _dry = ["--dry-run"] if req.dry_run else []
    steps_cfg = [
        (
            "RBC Release",
            "Release-branch automation — GitHub RHOAI-Build-Config",
            [PYTHON, "-m", "src.rbc_release", req.previous_version, req.new_version] + _dry,
        ),
        (
            "RBC Main Onboard",
            "Main-branch catalog + Tekton file onboarding — GitHub",
            [PYTHON, "-m", "src.rbc_main_onboard", req.previous_version, req.new_version] + _dry,
        ),
        (
            "Konflux Onboard",
            "Clone, edit, commit, push and open MR — GitLab konflux-release-data",
            [
                PYTHON,
                str(REPO_ROOT / "rhoai_release_onboard.py"),
                req.previous_version,
                req.new_version,
            ]
            + _dry
            + ["--repo-dir", req.repo_dir],
        ),
    ]

    enabled = req.enabled_steps
    if len(enabled) < len(steps_cfg):
        enabled += [True] * (len(steps_cfg) - len(enabled))

    # Initialise step records and signal the frontend
    _jobs[job_id]["steps"] = [_new_step(name, desc) for name, desc, _ in steps_cfg]
    _jobs[job_id]["enabled_steps"] = enabled[:len(steps_cfg)]
    await queue.put(json.dumps({
        "type": "pipeline_start",
        "count": len(steps_cfg),
        "enabled_steps": enabled[:len(steps_cfg)],
    }))

    cancel = _cancel_events.get(job_id)
    failed_steps: list[int] = []
    skipped_steps: list[int] = []
    cancelled = False
    for i, (_, _, cmd) in enumerate(steps_cfg):
        if cancel and cancel.is_set():
            cancelled = True
            for j in range(i, len(steps_cfg)):
                _jobs[job_id]["steps"][j]["status"] = "cancelled"
                await queue.put(json.dumps({
                    "type": "step_end", "step": j, "status": "cancelled",
                }))
            break
        if not enabled[i]:
            _jobs[job_id]["steps"][i]["status"] = "skipped"
            skipped_steps.append(i)
            await queue.put(json.dumps({
                "type": "step_skip", "step": i, "status": "skipped",
            }))
            continue
        ok = await _run_step(job_id, i, cmd, queue)
        if not ok:
            failed_steps.append(i)
            if cancel and cancel.is_set():
                cancelled = True
                for j in range(i + 1, len(steps_cfg)):
                    _jobs[job_id]["steps"][j]["status"] = "cancelled"
                    await queue.put(json.dumps({
                        "type": "step_end", "step": j, "status": "cancelled",
                    }))
                break

    if cancelled:
        overall = "cancelled"
    else:
        ran_steps = [i for i in range(len(steps_cfg)) if enabled[i]]
        all_ok = len(failed_steps) == 0
        if not ran_steps:
            overall = "success"
        elif all_ok:
            overall = "success"
        elif len(failed_steps) < len(ran_steps):
            overall = "partial"
        else:
            overall = "failed"

    _jobs[job_id]["status"] = overall
    await queue.put(
        json.dumps(
            {
                "type": "pipeline_end",
                "status": overall,
                "failed_steps": failed_steps,
                "pr_url": _jobs[job_id].get("pr_url"),
                "mr_url": _jobs[job_id].get("mr_url"),
            }
        )
    )
    await queue.put("[DONE]")
    _cancel_events.pop(job_id, None)


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.get("/", response_class=HTMLResponse)
async def index() -> HTMLResponse:
    html_path = TEMPLATES / "index.html"
    if not html_path.exists():
        raise HTTPException(status_code=500, detail="templates/index.html not found")
    return HTMLResponse(content=html_path.read_text(encoding="utf-8"))


@app.post("/api/run")
async def start_run(req: RunRequest) -> dict:
    if not req.previous_version.strip() or not req.new_version.strip():
        raise HTTPException(status_code=422, detail="previous_version and new_version are required")
    job_id = str(uuid.uuid4())
    _jobs[job_id] = {
        "id": job_id,
        "previous_version": req.previous_version,
        "new_version": req.new_version,
        "dry_run": req.dry_run,
        "enabled_steps": req.enabled_steps,
        "status": "pending",
        "steps": [],
        "pr_url": None,
        "mr_url": None,
    }
    _queues[job_id] = asyncio.Queue()
    _cancel_events[job_id] = asyncio.Event()
    asyncio.create_task(_run_pipeline(job_id, req))
    return {"job_id": job_id}


@app.post("/api/stop/{job_id}")
async def stop_run(job_id: str) -> dict:
    if job_id not in _jobs:
        raise HTTPException(status_code=404, detail="Job not found")
    if _jobs[job_id]["status"] != "running":
        raise HTTPException(status_code=409, detail="Job is not running")

    cancel = _cancel_events.get(job_id)
    if cancel:
        cancel.set()

    proc = _active_procs.get(job_id)
    if proc and proc.returncode is None:
        try:
            proc.terminate()
        except ProcessLookupError:
            pass

    return {"status": "stopping", "job_id": job_id}


@app.get("/api/events/{job_id}")
async def events(job_id: str) -> StreamingResponse:
    if job_id not in _jobs:
        raise HTTPException(status_code=404, detail="Job not found")
    queue = _queues[job_id]

    async def generator():
        # Send current state first so a page-refresh reconnects cleanly
        snapshot = _jobs.get(job_id, {})
        yield f"data: {json.dumps({'type': 'snapshot', 'job': snapshot})}\n\n"

        if snapshot.get("status") in ("success", "failed", "partial", "cancelled"):
            yield f"data: {json.dumps({'type': 'done'})}\n\n"
            return

        while True:
            try:
                msg = await asyncio.wait_for(queue.get(), timeout=25.0)
            except asyncio.TimeoutError:
                # Send a keep-alive comment so the browser doesn't time out
                yield ": keep-alive\n\n"
                continue
            if msg == "[DONE]":
                yield f"data: {json.dumps({'type': 'done'})}\n\n"
                break
            yield f"data: {msg}\n\n"

    return StreamingResponse(
        generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@app.get("/api/status/{job_id}")
async def status(job_id: str) -> dict:
    if job_id not in _jobs:
        raise HTTPException(status_code=404, detail="Job not found")
    return _jobs[job_id]


@app.get("/api/jobs")
async def list_jobs() -> list:
    return [
        {
            "id": j["id"],
            "previous_version": j["previous_version"],
            "new_version": j["new_version"],
            "status": j["status"],
            "dry_run": j["dry_run"],
        }
        for j in _jobs.values()
    ]
