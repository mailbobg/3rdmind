"""Local, persisted backtest jobs on top of RD-Agent research output. Registered under the server's auth gate."""
import json
import os
import subprocess
import sys
import uuid
from pathlib import Path

from flask import Blueprint, jsonify, request
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
    """Messages of a loaded trace, or None when the server has not loaded it."""
    from rdagent.log.server import app as server

    task = server.rdagent_processes.get(str(server.log_folder_path / trace_id))
    return None if task is None else task.messages


def metric_rounds(messages):
    rounds = []
    for message in messages:
        if message.get("tag") != "feedback.metric":
            continue
        content = message.get("content", {})
        try:
            metrics = json.loads(content["result"]) if isinstance(content.get("result"), str) else content.get("result") or {}
        except (ValueError, TypeError):
            metrics = {}
        rounds.append({
            "loop_id": message.get("loop_id"),
            "factors": [f["name"] for f in content.get("workspaces", {}).get("factors", [])],
            "paths": {f["name"]: f["path"] for f in content.get("workspaces", {}).get("factors", [])},
            "metrics": {k: v for k, v in metrics.items() if isinstance(v, (int, float))},
        })
    return rounds


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
            jobs.append({"id": path.parent.name, "config": json.loads(path.read_text()), "status": result["status"]})
        return jsonify(jobs)
    body = request.get_json() or {}
    try:
        messages = trace_messages(str(body.get("trace", "")))
        if messages is None:
            raise ValueError("Trace is not loaded on this server")
        body["factors"] = resolve_factor_paths(messages, body.get("loop_id"), body.get("factors") or [])
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
    return jsonify({"id": job_id, "config": json.loads((folder / "config.json").read_text()), **result})
