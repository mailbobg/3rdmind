"""Local, persisted backtest jobs on top of RD-Agent research output. Registered under the server's auth gate."""
import json
import os
import subprocess
import sys
import uuid
from pathlib import Path

from flask import Blueprint, current_app, jsonify, request
from rdagent.core.conf import RD_AGENT_SETTINGS
from rdagent.log.ui.conf import UI_SETTING
from rdagent.log.server.studio_worker import validate_config, write_json

studio = Blueprint("studio", __name__, url_prefix="/studio")
PROCESSES = {}
TRACE_ROOT = Path(UI_SETTING.trace_folder).resolve()
ROOT = TRACE_ROOT / "studio_backtests"
WORKSPACE_ROOT = Path(RD_AGENT_SETTINGS.workspace_path).resolve()


def job_folder(job_id):
    uuid.UUID(job_id)
    return ROOT / job_id


def trace_messages(trace_id):
    """Messages of a loaded trace, or None when the server has not loaded it.

    Reached via flask.current_app rather than `import rdagent.log.server.app`: the
    server is launched with `python -m rdagent.log.server.app`, which binds that
    module to sys.modules["__main__"]; importing it by its normal dotted name here
    would create a second, empty copy of the module (and an empty rdagent_processes
    registry), so /studio endpoints would never see the loaded trace.
    """
    registry = current_app.config["RDAGENT_PROCESSES"]
    task = registry.get(str(Path(current_app.config["LOG_FOLDER_PATH"]) / trace_id))
    return None if task is None else task.messages


def normalize_loop_id(value):
    """Coerce a loop_id to int; accepts int (not bool) or a string of digits (after strip).

    Persisted trace events (see extract_loopid_func_name in rdagent/log/ui/storage.py) always carry
    loop_id as a string, while live in-memory events may carry it as an int. Both /studio/rounds and
    /studio/backtests must agree on one representation or `round_["loop_id"] == loop_id` silently
    fails on a type mismatch (e.g. int 0 vs string "0").
    """
    if not isinstance(value, bool) and isinstance(value, int):
        return value
    if isinstance(value, str) and value.strip().lstrip("-").isdigit():
        return int(value)
    raise ValueError("loop_id must be an integer")


def metric_rounds(messages):
    """One entry per loop_id, in first-seen order; a repeated loop_id keeps its LATEST metric event."""
    order = []
    by_loop = {}
    for message in messages:
        if message.get("tag") != "feedback.metric":
            continue
        content = message.get("content", {})
        try:
            metrics = json.loads(content["result"]) if isinstance(content.get("result"), str) else content.get("result") or {}
        except (ValueError, TypeError):
            metrics = {}
        raw_loop_id = message.get("loop_id")
        try:
            loop_id = normalize_loop_id(raw_loop_id)
        except ValueError:
            loop_id = raw_loop_id
        if loop_id not in by_loop:
            order.append(loop_id)
        by_loop[loop_id] = {
            "loop_id": loop_id,
            "factors": [f["name"] for f in content.get("workspaces", {}).get("factors", [])],
            "paths": {f["name"]: f["path"] for f in content.get("workspaces", {}).get("factors", [])},
            "metrics": {k: v for k, v in metrics.items() if isinstance(v, (int, float)) and not isinstance(v, bool)},
        }
    return [by_loop[loop_id] for loop_id in order]


def resolve_factor_paths(messages, loop_id, factors):
    """Attach workspace paths to the requested factor names; reject unknown names or paths outside the workspace root."""
    paths = {}
    for round_ in metric_rounds(messages):
        if round_["loop_id"] == loop_id:
            paths = round_["paths"]
    if not paths:
        raise ValueError(f"Round {loop_id} has no factor workspaces")
    resolved = []
    for factor in factors:
        if not isinstance(factor, dict):
            raise ValueError("Each factor must be an object with name and weight")
        name = factor.get("name")
        if name not in paths:
            raise ValueError(f"Unknown factor {name!r} in round {loop_id}")
        path = Path(paths[name]).resolve()
        if WORKSPACE_ROOT not in path.parents:
            raise ValueError(f"Factor {name} lives outside the RD-Agent workspace root")
        if not (path / "result.h5").is_file():
            raise ValueError(f"Factor {name} has no result.h5")
        resolved.append({"name": name, "weight": float(factor.get("weight", 1)), "path": str(path)})
    return resolved


def public_config(config):
    """A copy of ``config`` with each factor's on-disk workspace ``path`` stripped for API responses."""
    public = dict(config)
    public["factors"] = [{"name": f["name"], "weight": f["weight"]} for f in config.get("factors", [])]
    return public


@studio.get("/environment")
def environment():
    provider = Path(os.environ.get("QLIB_PROVIDER_URI", "~/.qlib/qlib_data/cn_data")).expanduser()
    calendar = provider / "calendars" / "day.txt"
    dates = calendar.read_text().splitlines() if calendar.is_file() else []
    return jsonify({"chat_model": os.environ.get("LITELLM_CHAT_MODEL", os.environ.get("CHAT_MODEL", "")),
                    "provider_uri": str(provider), "data_ready": bool(dates),
                    "start": dates[0] if dates else None, "end": dates[-1] if dates else None,
                    "python": os.environ.get("STUDIO_PYTHON", sys.executable)})


@studio.get("/strategy")
def strategy_source():
    return jsonify({"name": "studio_worker.py", "code": Path(__file__).with_name("studio_worker.py").read_text()})


@studio.get("/rounds")
def rounds():
    trace_id = request.args.get("trace", "")
    messages = trace_messages(trace_id) if trace_id else None
    if messages is None:
        return jsonify({"error": "Trace is not loaded on this server"}), 404
    return jsonify([{k: v for k, v in r.items() if k != "paths"} for r in metric_rounds(messages)])


@studio.route("/backtests", methods=["GET", "POST"])
def backtests():
    ROOT.mkdir(parents=True, exist_ok=True)
    if request.method == "GET":
        jobs = []
        for path in sorted(ROOT.glob("*/config.json"), key=lambda p: p.stat().st_mtime, reverse=True)[:100]:
            result_path = path.parent / "result.json"
            result = json.loads(result_path.read_text()) if result_path.exists() else {"status": "queued"}
            jobs.append({"id": path.parent.name, "config": public_config(json.loads(path.read_text())), "status": result["status"]})
        return jsonify(jobs)
    body = request.get_json() or {}
    try:
        messages = trace_messages(str(body.get("trace", "")))
        if messages is None:
            raise ValueError("Trace is not loaded on this server")
        loop_id = normalize_loop_id(body.get("loop_id"))
        body["loop_id"] = loop_id
        body["factors"] = resolve_factor_paths(messages, loop_id, body.get("factors") or [])
        config = validate_config(body)
        config["provider_uri"] = str(Path(config.get("provider_uri") or os.environ.get(
            "QLIB_PROVIDER_URI", "~/.qlib/qlib_data/cn_data")).expanduser())
        if not (Path(config["provider_uri"]) / "calendars" / "day.txt").is_file():
            raise ValueError("Qlib data not found. Configure a local Qlib daily data directory first.")
    except (ValueError, TypeError, KeyError) as error:
        return jsonify({"error": str(error)}), 400
    job_id = str(uuid.uuid4())
    folder = job_folder(job_id)
    folder.mkdir()
    write_json(folder / "config.json", config)
    write_json(folder / "result.json", {"status": "queued"})
    try:
        with (folder / "stdout.log").open("w") as log:
            PROCESSES[job_id] = subprocess.Popen(
                [os.environ.get("STUDIO_PYTHON", sys.executable),
                 str(Path(__file__).with_name("studio_worker.py")), str(folder)],
                stdout=log, stderr=subprocess.STDOUT, start_new_session=True,
            )
    except OSError as error:
        write_json(folder / "result.json", {"status": "failed", "error": str(error)})
        return jsonify({"error": str(error)}), 500
    return jsonify({"id": job_id}), 202


@studio.get("/backtests/<job_id>")
def backtest_result(job_id):
    try:
        folder = job_folder(job_id)
    except ValueError:
        return jsonify({"error": "Invalid job ID"}), 400
    if not (folder / "result.json").exists():
        return jsonify({"error": "Job not found"}), 404
    result = json.loads((folder / "result.json").read_text())
    process = PROCESSES.get(job_id)
    if process is not None and process.poll() is not None:
        if result["status"] in ("running", "queued"):
            result = {"status": "failed", "error": "Worker exited without a result; inspect execution log."}
            write_json(folder / "result.json", result)
        PROCESSES.pop(job_id, None)
    log = folder / "stdout.log"
    if log.exists():
        with log.open("rb") as stream:
            stream.seek(max(0, log.stat().st_size - 16000))
            result["log"] = stream.read().decode("utf-8", errors="replace")
    return jsonify({"id": job_id, "config": public_config(json.loads((folder / "config.json").read_text())), **result})
