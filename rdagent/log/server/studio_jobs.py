"""Registry of the Studio's background work, so every long task looks the same to the UI.

A job is a small dict: id, kind (backtest, search, diagnose, refresh, universe, strategy_update, build, ...),
label, status (queued / running / completed / failed), progress {done, total}, message, market, link
{page, id} (where the UI opens it), started, finished, error and a small result. Two ways in:

* ``run(kind, label, fn)`` executes ``fn(job)`` on a daemon thread; the function may call ``update`` for
  progress and returns the job's result. Exceptions mark the job failed with their message.
* ``track(kind, label, poll)`` registers work that lives elsewhere (a subprocess writing a result.json); ``poll()``
  returns ``{"status", "progress", "error", "result"}`` and is consulted whenever the job is listed.

Finished jobs are kept in memory for a while (``KEEP``) so completion can be noticed by a poller that asks for
everything since its last look.
"""
from __future__ import annotations

import threading
import traceback
import uuid
from datetime import datetime, timezone

KEEP = 200
_lock = threading.RLock()
_jobs: dict[str, dict] = {}
_polls: dict[str, callable] = {}
_order: list[str] = []


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def create(kind: str, label: str, *, market: str | None = None, link: dict | None = None, total: int | None = None,
           status: str = "queued", job_id: str | None = None) -> dict:
    job = {"id": job_id or str(uuid.uuid4()), "kind": kind, "label": label, "status": status,
           "progress": {"done": 0, "total": total} if total is not None else None, "message": "",
           "market": market, "link": link, "started": _now(), "finished": None, "error": None, "result": None}
    with _lock:
        _jobs[job["id"]] = job
        _order.append(job["id"])
        _prune()
    return job


def update(job_id: str, *, done: int | None = None, total: int | None = None, message: str | None = None) -> None:
    with _lock:
        job = _jobs.get(job_id)
        if not job:
            return
        if done is not None or total is not None:
            progress = job.get("progress") or {"done": 0, "total": None}
            if done is not None:
                progress["done"] = done
            if total is not None:
                progress["total"] = total
            job["progress"] = progress
        if message is not None:
            job["message"] = message


def finish(job_id: str, status: str = "completed", *, error: str | None = None, result=None) -> None:
    with _lock:
        job = _jobs.get(job_id)
        if not job:
            return
        job.update({"status": status, "finished": _now(), "error": error})
        if result is not None:
            job["result"] = result
        if job.get("progress") and status == "completed":
            job["progress"]["done"] = job["progress"].get("total") or job["progress"]["done"]
        _polls.pop(job_id, None)


def run(kind: str, label: str, fn, *, market: str | None = None, link: dict | None = None, total: int | None = None) -> dict:
    """Start ``fn(job)`` on a thread; its return value becomes the job's result."""
    job = create(kind, label, market=market, link=link, total=total, status="running")

    def worker():
        try:
            result = fn(job)
        except Exception as error:  # noqa: BLE001 - the message is the user's diagnosis
            traceback.print_exc()
            finish(job["id"], "failed", error=str(error)[:500])
        else:
            finish(job["id"], "completed", result=result)

    threading.Thread(target=worker, name=f"studio-job-{kind}", daemon=True).start()
    return job


def track(kind: str, label: str, poll, *, market: str | None = None, link: dict | None = None, job_id: str | None = None) -> dict:
    """Register work running elsewhere; ``poll()`` reports its state whenever the job is listed."""
    job = create(kind, label, market=market, link=link, status="running", job_id=job_id)
    with _lock:
        _polls[job["id"]] = poll
    _refresh(job["id"])
    return job


def _refresh(job_id: str) -> None:
    with _lock:
        job, poll = _jobs.get(job_id), _polls.get(job_id)
    if not job or not poll or job["status"] in ("completed", "failed"):
        return
    try:
        state = poll() or {}
    except Exception as error:  # noqa: BLE001
        state = {"status": "failed", "error": f"status unreadable: {error}"}
    with _lock:
        if state.get("progress") is not None:
            job["progress"] = state["progress"]
        if state.get("message") is not None:
            job["message"] = state["message"]
        status = state.get("status")
        if status in ("completed", "failed"):
            finish(job_id, status, error=state.get("error"), result=state.get("result"))
        elif status in ("queued", "running"):
            job["status"] = status


def get(job_id: str) -> dict | None:
    _refresh(job_id)
    with _lock:
        job = _jobs.get(job_id)
        return dict(job) if job else None


def list_jobs(*, since: str | None = None, active_only: bool = False) -> list[dict]:
    """Jobs newest first: all active ones, plus finished ones that ended after ``since`` (or all kept ones)."""
    with _lock:
        ids = list(_order)
    for job_id in ids:
        _refresh(job_id)
    out = []
    with _lock:
        for job_id in reversed(ids):
            job = _jobs.get(job_id)
            if not job:
                continue
            active = job["status"] in ("queued", "running")
            if active or (not active_only and (since is None or (job.get("finished") or "") > since)):
                out.append(dict(job))
    return out


def find(kind: str, **match) -> dict | None:
    """The newest active job of ``kind`` whose link matches ``match`` (e.g. id=...), or None."""
    with _lock:
        for job_id in reversed(_order):
            job = _jobs.get(job_id)
            if job and job["kind"] == kind and job["status"] in ("queued", "running") and all((job.get("link") or {}).get(k) == v for k, v in match.items()):
                return dict(job)
    return None


def _prune() -> None:
    done = [j for j in _order if _jobs[j]["status"] in ("completed", "failed")]
    for job_id in done[:-KEEP] if len(done) > KEEP else []:
        _jobs.pop(job_id, None)
        _polls.pop(job_id, None)
        _order.remove(job_id)


def reset() -> None:
    """Forget everything (tests)."""
    with _lock:
        _jobs.clear()
        _polls.clear()
        _order.clear()
