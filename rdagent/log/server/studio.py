"""Local, persisted backtest jobs on top of RD-Agent research output. Registered under the server's auth gate."""
import hashlib
import json
import os
import subprocess
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

from flask import Blueprint, Response, current_app, jsonify, request
from rdagent.core.conf import RD_AGENT_SETTINGS
from rdagent.log.ui.conf import UI_SETTING
from rdagent.log.server.studio_worker import validate_config, write_json

studio = Blueprint("studio", __name__, url_prefix="/studio")
PROCESSES = {}
TRACE_ROOT = Path(UI_SETTING.trace_folder).resolve()
ROOT = TRACE_ROOT / "studio_backtests"
SEARCH_ROOT = TRACE_ROOT / "studio_searches"
STRATEGY_ROOT = TRACE_ROOT / "studio_strategies"
# Factors recomputed on the latest data ("重算到最新") live here, one folder per (trace, round, name),
# beside the shared daily_pv the recomputation reads.
REFRESH_ROOT = TRACE_ROOT / "studio_refresh"
LATEST_DATA = TRACE_ROOT / "studio_data" / "daily_pv_latest.h5"
# Instrument code → {name, industry}; a JSON file the user refreshes from their own listing source.
INSTRUMENT_NAMES = TRACE_ROOT / "studio_data" / "instrument_names.json"
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
        workspaces = content.get("workspaces", {}) or {}
        by_loop[loop_id] = {
            "loop_id": loop_id,
            "factors": [f["name"] for f in workspaces.get("factors", [])],
            "paths": {f["name"]: f["path"] for f in workspaces.get("factors", [])},
            "experiment": workspaces.get("experiment"),
            "metrics": {k: v for k, v in metrics.items() if isinstance(v, (int, float)) and not isinstance(v, bool)},
        }
    return [by_loop[loop_id] for loop_id in order]


def prediction_file(experiment_path):
    """The newest Qlib ``pred.pkl`` recorded under an experiment workspace, or None."""
    if not experiment_path:
        return None
    root = Path(experiment_path).resolve()
    if WORKSPACE_ROOT not in root.parents:
        return None
    candidates = sorted(root.glob("mlruns/*/*/artifacts/pred.pkl"), key=lambda p: p.stat().st_mtime)
    return candidates[-1] if candidates else None


def factor_code(messages, loop_id, name):
    """The generated factor.py for ``name`` in round ``loop_id``, or None when the trace has no code event for it."""
    code = None
    for message in messages:
        if message.get("tag") != "evolving.codes":
            continue
        try:
            if normalize_loop_id(message.get("loop_id")) != loop_id:
                continue
        except ValueError:
            continue
        for task in message.get("content") or []:
            if task.get("target_task_name") == name and isinstance(task.get("workspace"), dict):
                code = task["workspace"].get("factor.py", code)
    return code


def round_context(messages):
    """Per loop_id: the agent's hypothesis, its verdict, and each task's description/formulation/variables."""
    context = {}
    for message in messages:
        try:
            loop_id = normalize_loop_id(message.get("loop_id"))
        except ValueError:
            continue
        entry = context.setdefault(loop_id, {"hypothesis": None, "decision": None, "reason": None, "tasks": {}})
        tag, content = message.get("tag"), message.get("content") or {}
        if tag == "research.hypothesis" and isinstance(content, dict):
            entry["hypothesis"] = content.get("hypothesis")
        elif tag == "feedback.hypothesis_feedback" and isinstance(content, dict):
            entry["decision"] = content.get("decision")
            entry["reason"] = content.get("reason") or content.get("hypothesis_evaluation")
        elif tag == "research.tasks":
            for task in content if isinstance(content, list) else [content]:
                if isinstance(task, dict) and task.get("name"):
                    entry["tasks"][task["name"]] = {k: task.get(k) for k in ("description", "formulation", "variables")}
    return context


def task_fallback(registry, name):
    """A resumed run replays no task/hypothesis events; borrow them from any loaded trace that proposed ``name``.

    Returns the task detail plus the hypothesis of the round that proposed it (under "hypothesis").
    """
    for task in registry.values():
        for entry in round_context(task.messages).values():
            if name in entry["tasks"] and entry["tasks"][name].get("description"):
                return {**entry["tasks"][name], "hypothesis": entry["hypothesis"]}
    return {}


def analysis_cache_path(workspace, market):
    return Path(workspace) / f"studio_analysis.{market}.json"


def cached_analysis(workspace, market):
    """The stored single-factor analysis, or None when absent or older than result.h5."""
    path = analysis_cache_path(workspace, market)
    source = Path(workspace) / "result.h5"
    if not path.is_file() or not source.is_file():
        return None
    try:
        data = json.loads(path.read_text())
    except ValueError:
        return None
    if data.get("source_mtime") != source.stat().st_mtime or data.get("status") != "completed":
        return None
    return data


def refresh_dir(trace, loop_id, name):
    return REFRESH_ROOT / hashlib.sha1(f"{trace}#{loop_id}#{name}".encode()).hexdigest()[:16]


def refreshed_meta(trace, loop_id, name):
    """meta.json of a recomputed factor, or None when it has never been recomputed."""
    folder = refresh_dir(trace, loop_id, name)
    if not (folder / "result.h5").is_file() or not (folder / "meta.json").is_file():
        return None
    try:
        return json.loads((folder / "meta.json").read_text())
    except ValueError:
        return None


def signal_workspace(trace, loop_id, name, workspace):
    """Where a factor's result.h5 is read from: the recomputed copy when there is one, else RD-Agent's workspace."""
    return refresh_dir(trace, loop_id, name) if refreshed_meta(trace, loop_id, name) else Path(workspace)


def run_refresh(code_path, name, out_dir):
    """Recompute one factor on the latest data in a subprocess; returns its meta on success."""
    provider = str(Path(os.environ.get("QLIB_PROVIDER_URI", "~/.qlib/qlib_data/cn_data")).expanduser())
    start = os.environ.get("STUDIO_REFRESH_START", "2022-10-10")
    completed = subprocess.run(
        [os.environ.get("STUDIO_PYTHON", sys.executable), str(Path(__file__).with_name("studio_refresh.py")),
         provider, str(LATEST_DATA), start, str(code_path), name, str(out_dir)],
        capture_output=True, text=True, timeout=1500,
    )
    line = completed.stdout.strip().splitlines()[-1] if completed.stdout.strip() else ""
    try:
        data = json.loads(line)
    except ValueError:
        raise RuntimeError(completed.stderr.strip().splitlines()[-1] if completed.stderr.strip() else "refresh produced no output")
    if data.get("status") != "completed":
        raise RuntimeError(data.get("error") or "refresh failed")
    return data


def factor_library(registry, log_folder):
    """Every factor with a workspace across all loaded traces, newest trace first."""
    root = Path(log_folder)
    entries = []
    for key, task in registry.items():
        try:
            trace = Path(key).relative_to(root).as_posix()
        except ValueError:
            continue
        context = round_context(task.messages)
        for round_ in metric_rounds(task.messages):
            round_ctx = context.get(round_["loop_id"], {"hypothesis": None, "decision": None, "reason": None, "tasks": {}})
            for name in round_["factors"]:
                code = factor_code(task.messages, round_["loop_id"], name)
                workspace = Path(round_["paths"].get(name, "")).resolve()
                if code is None and WORKSPACE_ROOT in workspace.parents and (workspace / "factor.py").is_file():
                    # A resumed run replays no code events; fall back to the factor.py left in its workspace.
                    code = (workspace / "factor.py").read_text(errors="replace")
                detail = round_ctx["tasks"].get(name) or task_fallback(registry, name)
                refreshed = refreshed_meta(trace, round_["loop_id"], name)
                effective = refresh_dir(trace, round_["loop_id"], name) if refreshed else workspace
                analysis = cached_analysis(effective, "csi300") if refreshed or WORKSPACE_ROOT in workspace.parents else None
                entries.append({
                    "trace": trace, "loop_id": round_["loop_id"], "name": name,
                    "description": detail.get("description"), "formulation": detail.get("formulation"),
                    "variables": detail.get("variables"),
                    "hypothesis": round_ctx["hypothesis"] or detail.get("hypothesis"),
                    "decision": round_ctx["decision"], "reason": round_ctx["reason"],
                    "metrics": round_["metrics"], "code": code,
                    "analysis": analysis,
                    "refreshed": refreshed,
                    "coverage": ({"start": refreshed["start"], "end": refreshed["end"]} if refreshed
                                 else analysis.get("coverage") if analysis else None),
                })
    return entries


def factor_workspace(trace, loop_id, name):
    """Resolve one library factor to its workspace path, with the same guards as a backtest request."""
    resolved = resolve_factor_paths(trace, loop_id, [{"name": name, "weight": 1}])
    return Path(resolved[0]["path"])


def analyze_factor(workspace, market):
    """Run (or reuse) the single-factor analysis for ``workspace`` inside ``market``."""
    cached = cached_analysis(workspace, market)
    if cached is not None:
        return cached
    provider = str(Path(os.environ.get("QLIB_PROVIDER_URI", "~/.qlib/qlib_data/cn_data")).expanduser())
    output = analysis_cache_path(workspace, market)
    completed = subprocess.run(
        [os.environ.get("STUDIO_PYTHON", sys.executable), str(Path(__file__).with_name("studio_analysis.py")),
         str(workspace), provider, market, str(output)],
        capture_output=True, text=True, timeout=300,
    )
    if not output.is_file():
        raise RuntimeError(completed.stderr.strip().splitlines()[-1] if completed.stderr.strip() else "analysis produced no output")
    data = json.loads(output.read_text())
    if data.get("status") != "completed":
        raise RuntimeError(data.get("error") or "analysis failed")
    data["source_mtime"] = (Path(workspace) / "result.h5").stat().st_mtime
    output.write_text(json.dumps(data, ensure_ascii=False, allow_nan=False))
    return data


def factor_correlation(workspaces):
    """Mean daily cross-sectional Spearman correlation between factors, over the dates they all share."""
    import pandas as pd

    frames = []
    for name, workspace in workspaces:
        frame = pd.read_hdf(Path(workspace) / "result.h5")
        if isinstance(frame, pd.Series):
            frame = frame.to_frame()
        frames.append(frame.iloc[:, 0].rename(name))
    joined = pd.concat(frames, axis=1).dropna()
    if joined.empty:
        raise ValueError("The selected factors share no observations")
    ranks = joined.groupby(level="datetime").rank(pct=True)
    days = ranks.index.get_level_values("datetime").unique()
    # Averaging per-day correlation matrices is O(days); sampling every k-th day keeps large baskets responsive.
    step = max(1, len(days) // 250)
    sampled = ranks[ranks.index.get_level_values("datetime").isin(days[::step])]
    matrix = sampled.groupby(level="datetime").corr().groupby(level=1).mean()
    names = [name for name, _ in workspaces]
    matrix = matrix.loc[names, names]
    return {"names": names, "matrix": [[float(v) for v in row] for row in matrix.values], "days": int(len(days))}


def resolve_factor_paths(default_trace, default_loop_id, factors, prefer_refreshed=True):
    """Attach workspace paths to the requested factors.

    Each factor may name its own ``trace``/``loop_id`` (a basket built from several rounds); otherwise the
    request-level defaults apply. Unknown names, unloaded traces, paths outside the workspace root and
    missing result.h5 files are all rejected.
    """
    resolved = []
    for factor in factors:
        if not isinstance(factor, dict):
            raise ValueError("Each factor must be an object with name and weight")
        name = factor.get("name")
        trace = factor.get("trace") or default_trace
        loop_id = normalize_loop_id(factor.get("loop_id", default_loop_id))
        messages = trace_messages(str(trace or ""))
        if messages is None:
            raise ValueError(f"Trace {trace!r} is not loaded on this server")
        round_ = next((r for r in metric_rounds(messages) if r["loop_id"] == loop_id), None)
        if round_ is None:
            raise ValueError(f"Round {loop_id} of {trace} has no evaluation")
        kind = factor.get("kind", "factor")
        if kind == "prediction":
            # The round's Qlib model predictions (pred.pkl) used directly as the signal.
            path = prediction_file(round_["experiment"])
            if path is None:
                raise ValueError(f"Round {loop_id} of {trace} recorded no model prediction")
        elif kind == "factor":
            paths = round_["paths"]
            if name not in paths:
                raise ValueError(f"Unknown factor {name!r} in round {loop_id} of {trace}")
            path = Path(paths[name]).resolve()
            if WORKSPACE_ROOT not in path.parents:
                raise ValueError(f"Factor {name} lives outside the RD-Agent workspace root")
            if prefer_refreshed:
                path = signal_workspace(trace, loop_id, name, path)
            if not (path / "result.h5").is_file():
                raise ValueError(f"Factor {name} has no result.h5")
        else:
            raise ValueError(f"Unknown signal kind {kind!r}")
        resolved.append({"name": name, "kind": kind, "weight": float(factor.get("weight", 1)), "path": str(path),
                         "trace": trace, "loop_id": loop_id})
    return resolved


def public_config(config):
    """A copy of ``config`` with each factor's on-disk workspace ``path`` stripped for API responses."""
    public = dict(config)
    public["factors"] = [{k: f[k] for k in ("name", "kind", "weight", "trace", "loop_id") if k in f} for f in config.get("factors", [])]
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


@studio.get("/trace-status")
def trace_status():
    """Whether a trace is known to this server and whether its RD-Agent process is still running.

    A freshly launched run has no events for a while; the UI uses this to tell "starting" apart from
    "not loaded" and "finished without events".
    """
    trace_id = request.args.get("trace", "")
    registry = current_app.config["RDAGENT_PROCESSES"]
    task = registry.get(str(Path(current_app.config["LOG_FOLDER_PATH"]) / trace_id)) if trace_id else None
    if task is None:
        return jsonify({"loaded": False, "alive": False, "messages": 0})
    alive = task.process is not None and task.is_alive()
    return jsonify({"loaded": True, "alive": bool(alive), "messages": len(task.messages)})


def summarize_task(trace_id, task):
    """One row of the experiment list: what a user needs to pick a run without loading it.

    Everything comes from the messages already held in memory, so this is cheap enough to compute
    for every loaded trace on each request.
    """
    loops, accepted, hypothesis, end, updated, ended_at = set(), 0, None, None, "", ""
    for message in task.messages:
        try:
            loops.add(normalize_loop_id(message.get("loop_id")))
        except ValueError:
            pass
        tag, content = message.get("tag") or "", message.get("content") or {}
        if tag == "research.hypothesis" and isinstance(content, dict):
            hypothesis = content.get("hypothesis") or hypothesis
        elif tag == "feedback.hypothesis_feedback" and isinstance(content, dict) and content.get("decision") is True:
            accepted += 1
        timestamp = str(message.get("timestamp") or "")
        if tag.lower() == "end":
            # The END event of a trace read back from disk is stamped when the server loads it, not when
            # the run finished, so it only stands in for "updated" when nothing else is there.
            end, ended_at = (content if isinstance(content, dict) else {}), max(ended_at, timestamp)
        else:
            updated = max(updated, timestamp)
    process = getattr(task, "process", None)
    alive = process is not None and task.is_alive()
    if end is not None:
        code = end.get("end_code")
        status = "completed" if code == 0 else "stopped" if code == -1 else "failed"
    elif alive:
        status = "running" if task.messages else "starting"
    else:
        status = "ended"
    return {
        "id": trace_id, "scenario": trace_id.split("/")[0], "rounds": len(loops), "accepted": accepted,
        "status": status, "updated": updated or ended_at or None, "hypothesis": hypothesis, "messages": len(task.messages),
    }


@studio.get("/experiments")
def experiments():
    """Summaries of every trace this server has loaded (running or read back from disk)."""
    registry = current_app.config["RDAGENT_PROCESSES"]
    root = Path(current_app.config["LOG_FOLDER_PATH"])
    rows = []
    for key, task in list(registry.items()):
        if task is None:
            continue
        try:
            trace_id = Path(key).relative_to(root).as_posix()
        except ValueError:
            trace_id = key
        rows.append(summarize_task(trace_id, task))
    return jsonify(rows)


@studio.get("/rounds")
def rounds():
    trace_id = request.args.get("trace", "")
    messages = trace_messages(trace_id) if trace_id else None
    if messages is None:
        return jsonify({"error": "Trace is not loaded on this server"}), 404
    return jsonify([
        {**{k: v for k, v in r.items() if k not in ("paths", "experiment")},
         "prediction": prediction_file(r["experiment"]) is not None}
        for r in metric_rounds(messages)
    ])


@studio.get("/factors")
def factors():
    return jsonify(factor_library(current_app.config["RDAGENT_PROCESSES"], current_app.config["LOG_FOLDER_PATH"]))


@studio.get("/factors/analysis")
def factor_analysis():
    market = request.args.get("market", "csi300")
    if market not in ("csi300", "csi500", "all"):
        return jsonify({"error": "Unsupported instrument universe"}), 400
    try:
        workspace = factor_workspace(request.args.get("trace", ""), request.args.get("loop_id"), request.args.get("name", ""))
        return jsonify(analyze_factor(workspace, market))
    except (ValueError, TypeError, KeyError) as error:
        return jsonify({"error": str(error)}), 400
    except (RuntimeError, subprocess.TimeoutExpired) as error:
        return jsonify({"error": str(error)}), 500


def frame_coverage(frame):
    """First/last date and size of a signal frame, so the UI can warn before a backtest window misses it."""
    import pandas as pd

    level = "datetime" if "datetime" in (frame.index.names or []) else 0
    dates = pd.DatetimeIndex(frame.index.get_level_values(level))
    return {"start": str(dates.min().date()), "end": str(dates.max().date()), "days": int(dates.nunique()), "rows": int(len(frame))}


def prediction_coverage(path):
    import pandas as pd

    return frame_coverage(pd.read_pickle(path))


def factor_coverage(workspace):
    """Coverage of a factor's result.h5 without running the full single-factor analysis."""
    import pandas as pd

    return frame_coverage(pd.read_hdf(workspace / "result.h5"))


@studio.get("/predictions/coverage")
def predictions_coverage():
    try:
        resolved = resolve_factor_paths(request.args.get("trace", ""), request.args.get("loop_id"),
                                        [{"name": "prediction", "kind": "prediction"}])
        return jsonify(prediction_coverage(Path(resolved[0]["path"])))
    except (ValueError, TypeError, KeyError) as error:
        return jsonify({"error": str(error)}), 400


@studio.post("/factors/refresh")
def factors_refresh():
    """Recompute a factor's signal on the latest Qlib data; the copy then replaces the workspace result.h5 for Studio use."""
    body = request.get_json() or {}
    trace, name = str(body.get("trace") or ""), str(body.get("name") or "")
    try:
        loop_id = normalize_loop_id(body.get("loop_id"))
        original = Path(resolve_factor_paths(trace, loop_id, [{"name": name, "weight": 1}], prefer_refreshed=False)[0]["path"])
        code_path = original / "factor.py"
        if not code_path.is_file():
            code = factor_code(trace_messages(trace), loop_id, name)
            if not code:
                raise ValueError(f"No factor.py recorded for {name}")
            code_path = REFRESH_ROOT / "code" / f"{refresh_dir(trace, loop_id, name).name}.py"
            code_path.parent.mkdir(parents=True, exist_ok=True)
            code_path.write_text(code)
        out = refresh_dir(trace, loop_id, name)
        for stale in out.glob("studio_analysis.*.json"):
            stale.unlink()
        return jsonify(run_refresh(code_path, name, out))
    except (ValueError, TypeError, KeyError) as error:
        return jsonify({"error": str(error)}), 400
    except (RuntimeError, subprocess.TimeoutExpired) as error:
        return jsonify({"error": str(error)}), 500


@studio.get("/factors/coverage")
def factors_coverage():
    try:
        workspace = factor_workspace(request.args.get("trace", ""), request.args.get("loop_id"), request.args.get("name", ""))
        return jsonify(factor_coverage(workspace))
    except (ValueError, TypeError, KeyError, OSError) as error:
        return jsonify({"error": str(error)}), 400


@studio.post("/factors/correlation")
def factors_correlation():
    body = request.get_json() or {}
    try:
        refs = body.get("factors") or []
        if not isinstance(refs, list) or not 2 <= len(refs) <= 20:
            raise ValueError("Select 2 to 20 factors")
        workspaces = []
        for ref in refs:
            if not isinstance(ref, dict):
                raise ValueError("Each factor must be an object")
            workspaces.append((ref.get("name"), factor_workspace(ref.get("trace", ""), ref.get("loop_id"), ref.get("name", ""))))
        if len({name for name, _ in workspaces}) != len(workspaces):
            raise ValueError("Factor names in a basket must be unique")
        return jsonify(factor_correlation(workspaces))
    except (ValueError, TypeError, KeyError) as error:
        return jsonify({"error": str(error)}), 400


@studio.route("/backtests", methods=["GET", "POST"])
def backtests():
    ROOT.mkdir(parents=True, exist_ok=True)
    if request.method == "GET":
        jobs = []
        for path in sorted(ROOT.glob("*/config.json"), key=lambda p: p.stat().st_mtime, reverse=True)[:100]:
            result_path = path.parent / "result.json"
            result = json.loads(result_path.read_text()) if result_path.exists() else {"status": "queued"}
            jobs.append({"id": path.parent.name, "config": public_config(json.loads(path.read_text())), "status": result["status"],
                         "total_return": (result.get("metrics") or {}).get("total_return"),
                         "created": datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc).isoformat()})
        return jsonify(jobs)
    body = request.get_json() or {}
    try:
        config = prepare_backtest_config(body)
    except (ValueError, TypeError, KeyError) as error:
        return jsonify({"error": str(error)}), 400
    try:
        job_id = launch_backtest(config)
    except OSError as error:
        return jsonify({"error": str(error)}), 500
    return jsonify({"id": job_id}), 202


def prepare_backtest_config(body):
    """Resolve factor paths and validate a backtest request body into a worker config."""
    body = dict(body)
    # Request-level trace/loop_id are defaults for factors that do not name their own round.
    default_trace = str(body.get("trace") or "") or None
    default_loop = body.get("loop_id")
    if default_trace and trace_messages(default_trace) is None:
        raise ValueError("Trace is not loaded on this server")
    if default_loop is not None:
        body["loop_id"] = normalize_loop_id(default_loop)
    body["factors"] = resolve_factor_paths(default_trace, body.get("loop_id"), body.get("factors") or [])
    config = validate_config(body)
    config["provider_uri"] = str(Path(config.get("provider_uri") or os.environ.get(
        "QLIB_PROVIDER_URI", "~/.qlib/qlib_data/cn_data")).expanduser())
    if not (Path(config["provider_uri"]) / "calendars" / "day.txt").is_file():
        raise ValueError("Qlib data not found. Configure a local Qlib daily data directory first.")
    return config


def launch_backtest(config):
    """Write a job folder and start the worker; returns the job id. Raises OSError when the worker cannot start."""
    ROOT.mkdir(parents=True, exist_ok=True)
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
        raise
    return job_id


def search_folder(job_id):
    uuid.UUID(job_id)
    return SEARCH_ROOT / job_id


@studio.route("/searches", methods=["GET", "POST"])
def searches():
    """Greedy portfolio searches: same request shape as a backtest plus a `search` block (objective, split)."""
    SEARCH_ROOT.mkdir(parents=True, exist_ok=True)
    if request.method == "GET":
        jobs = []
        for path in sorted(SEARCH_ROOT.glob("*/config.json"), key=lambda p: p.stat().st_mtime, reverse=True)[:50]:
            result_path = path.parent / "result.json"
            result = json.loads(result_path.read_text()) if result_path.exists() else {"status": "queued"}
            config = public_config(json.loads(path.read_text()))
            jobs.append({"id": path.parent.name, "status": result["status"], "config": config,
                         "created": datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc).isoformat(),
                         "recommended": (result.get("recommended") or {}).get("members"),
                         "validation_return": ((result.get("recommended") or {}).get("validation") or {}).get("total_return")})
        return jsonify(jobs)
    body = request.get_json() or {}
    try:
        body["factors"] = resolve_factor_paths(None, None, body.get("factors") or [])
        body.setdefault("search", {})
        config = validate_config(body)
        config["provider_uri"] = str(Path(os.environ.get("QLIB_PROVIDER_URI", "~/.qlib/qlib_data/cn_data")).expanduser())
        if not (Path(config["provider_uri"]) / "calendars" / "day.txt").is_file():
            raise ValueError("Qlib data not found. Configure a local Qlib daily data directory first.")
        if len(config["factors"]) < 2:
            raise ValueError("Search needs at least two candidate signals")
    except (ValueError, TypeError, KeyError) as error:
        return jsonify({"error": str(error)}), 400
    job_id = str(uuid.uuid4())
    folder = search_folder(job_id)
    folder.mkdir()
    write_json(folder / "config.json", config)
    write_json(folder / "result.json", {"status": "queued"})
    try:
        with (folder / "stdout.log").open("w") as log:
            PROCESSES[f"search:{job_id}"] = subprocess.Popen(
                [os.environ.get("STUDIO_PYTHON", sys.executable),
                 str(Path(__file__).with_name("studio_worker.py")), str(folder), "--search"],
                stdout=log, stderr=subprocess.STDOUT, start_new_session=True,
            )
    except OSError as error:
        write_json(folder / "result.json", {"status": "failed", "error": str(error)})
        return jsonify({"error": str(error)}), 500
    return jsonify({"id": job_id}), 202


@studio.get("/searches/<job_id>")
def search_result(job_id):
    try:
        folder = search_folder(job_id)
    except ValueError:
        return jsonify({"error": "Invalid job ID"}), 400
    if not (folder / "result.json").exists():
        return jsonify({"error": "Job not found"}), 404
    result = json.loads((folder / "result.json").read_text())
    process = PROCESSES.get(f"search:{job_id}")
    if process is not None and process.poll() is not None:
        if result["status"] in ("running", "queued"):
            result = {"status": "failed", "error": "Worker exited without a result; inspect execution log."}
            write_json(folder / "result.json", result)
        PROCESSES.pop(f"search:{job_id}", None)
    log = folder / "stdout.log"
    if log.exists():
        with log.open("rb") as stream:
            stream.seek(max(0, log.stat().st_size - 16000))
            result["log"] = stream.read().decode("utf-8", errors="replace")
    result.pop("config", None)
    return jsonify({"id": job_id, "config": public_config(json.loads((folder / "config.json").read_text())), **result})


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
    result["breakdown"] = diagnosis_state(job_id, folder)
    return jsonify({"id": job_id, "config": public_config(json.loads((folder / "config.json").read_text())), **result})


def diagnosis_state(job_id, folder):
    """The take-apart diagnosis of a backtest (diagnosis.json), with a dead worker turned into a failure."""
    path = folder / "diagnosis.json"
    if not path.exists():
        return None
    state = json.loads(path.read_text())
    process = PROCESSES.get(f"{job_id}:diagnose")
    if process is not None and process.poll() is not None:
        if state.get("status") in ("running", "queued"):
            state = {"status": "failed", "error": "Diagnosis worker exited without a result; inspect execution log."}
            write_json(path, state)
        PROCESSES.pop(f"{job_id}:diagnose", None)
    return state


@studio.post("/backtests/<job_id>/diagnose")
def backtest_diagnose(job_id):
    """Start the take-apart diagnosis: every signal alone and the portfolio without each one, same window."""
    try:
        folder = job_folder(job_id)
    except ValueError:
        return jsonify({"error": "Invalid job ID"}), 400
    if not (folder / "result.json").exists():
        return jsonify({"error": "Job not found"}), 404
    result = json.loads((folder / "result.json").read_text())
    if result.get("status") != "completed":
        return jsonify({"error": "Diagnose a completed backtest"}), 409
    if len(json.loads((folder / "config.json").read_text()).get("factors") or []) < 2:
        return jsonify({"error": "Diagnosis needs at least two signals"}), 400
    running = PROCESSES.get(f"{job_id}:diagnose")
    if running is not None and running.poll() is None:
        return jsonify({"status": "running"}), 202
    write_json(folder / "diagnosis.json", {"status": "queued"})
    try:
        with (folder / "diagnosis.log").open("w") as log:
            PROCESSES[f"{job_id}:diagnose"] = subprocess.Popen(
                [os.environ.get("STUDIO_PYTHON", sys.executable),
                 str(Path(__file__).with_name("studio_worker.py")), str(folder), "--diagnose"],
                stdout=log, stderr=subprocess.STDOUT, start_new_session=True,
            )
    except OSError as error:
        write_json(folder / "diagnosis.json", {"status": "failed", "error": str(error)})
        return jsonify({"error": str(error)}), 500
    return jsonify({"status": "queued"}), 202


# ---- Strategies: a named factor portfolio with its evidence and its tracking runs -----------------------

STRATEGY_PARAMS = ("market", "benchmark", "topk", "n_drop", "account", "open_cost", "close_cost")


def strategy_path(strategy_id):
    uuid.UUID(strategy_id)
    return STRATEGY_ROOT / f"{strategy_id}.json"


def load_strategy(strategy_id):
    path = strategy_path(strategy_id)
    if not path.is_file():
        raise FileNotFoundError(strategy_id)
    return json.loads(path.read_text())


def save_strategy(strategy):
    STRATEGY_ROOT.mkdir(parents=True, exist_ok=True)
    strategy["updated"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    write_json(strategy_path(strategy["id"]), strategy)
    return strategy


def run_summary(job_id):
    """Status, window and headline metrics of one backtest job the strategy points at."""
    try:
        folder = job_folder(job_id)
    except ValueError:
        return {"id": job_id, "status": "missing"}
    if not (folder / "config.json").is_file():
        return {"id": job_id, "status": "missing"}
    config = json.loads((folder / "config.json").read_text())
    result = json.loads((folder / "result.json").read_text()) if (folder / "result.json").is_file() else {"status": "queued"}
    metrics = result.get("metrics") or {}
    return {"id": job_id, "status": result.get("status"), "start": config.get("start"), "end": config.get("end"),
            "total_return": metrics.get("total_return"), "sharpe": metrics.get("sharpe"), "max_drawdown": metrics.get("max_drawdown"),
            "benchmark_return": metrics.get("benchmark_return"), "error": result.get("error"),
            "created": datetime.fromtimestamp((folder / "config.json").stat().st_mtime, tz=timezone.utc).isoformat()}


def strategy_view(strategy):
    runs = [run_summary(r["backtest_id"]) | {"kind": r.get("kind", "update")} for r in strategy.get("runs", [])]
    return {**strategy, "run_details": runs}


def validate_strategy_body(body, existing=None):
    """Name, note, factors, model and parameters of a strategy; factors are resolved like a backtest request."""
    name = str(body.get("name", existing["name"] if existing else "")).strip()
    if not 1 <= len(name) <= 80:
        raise ValueError("策略名称需要 1 到 80 个字符")
    note = str(body.get("note", existing["note"] if existing else "") or "")[:2000]
    if existing is not None and "factors" not in body:
        return {**existing, "name": name, "note": note}
    factors = body.get("factors") or []
    resolved = resolve_factor_paths(None, None, factors)
    if not resolved:
        raise ValueError("策略至少需要一个信号")
    model = body.get("model") or {"method": "rank"}
    if not isinstance(model, dict) or model.get("method") not in ("rank", "lgbm"):
        raise ValueError("Unsupported signal method")
    params = {k: body.get("params", {}).get(k, body.get(k)) for k in STRATEGY_PARAMS}
    if any(params[k] is None for k in ("market", "topk", "n_drop")):
        raise ValueError("策略缺少市场或持仓参数")
    return {"name": name, "note": note, "model": model, "params": params,
            "factors": [{"name": f["name"], "kind": f["kind"], "weight": f["weight"], "trace": f["trace"], "loop_id": f["loop_id"]} for f in resolved]}


@studio.route("/strategies", methods=["GET", "POST"])
def strategies():
    STRATEGY_ROOT.mkdir(parents=True, exist_ok=True)
    if request.method == "GET":
        items = []
        for path in sorted(STRATEGY_ROOT.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True):
            try:
                strategy = json.loads(path.read_text())
            except ValueError:
                continue
            latest = run_summary(strategy["runs"][-1]["backtest_id"]) if strategy.get("runs") else None
            items.append({k: strategy.get(k) for k in ("id", "name", "note", "created", "updated", "factors", "model", "params", "evidence")} | {"latest": latest, "run_count": len(strategy.get("runs", []))})
        return jsonify(items)
    body = request.get_json() or {}
    try:
        fields = validate_strategy_body(body)
    except (ValueError, TypeError, KeyError) as error:
        return jsonify({"error": str(error)}), 400
    evidence = body.get("evidence") or {}
    runs = []
    if evidence.get("backtest_id"):
        try:
            job_folder(str(evidence["backtest_id"]))
            runs.append({"backtest_id": str(evidence["backtest_id"]), "kind": "evidence"})
        except ValueError:
            return jsonify({"error": "Invalid evidence backtest id"}), 400
    strategy = save_strategy({"id": str(uuid.uuid4()), "created": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                              **fields, "evidence": {k: evidence.get(k) for k in ("backtest_id", "search_id", "start", "end") if evidence.get(k)},
                              "runs": runs})
    return jsonify(strategy_view(strategy)), 201


@studio.route("/strategies/<strategy_id>", methods=["GET", "PATCH", "DELETE"])
def strategy_item(strategy_id):
    try:
        strategy = load_strategy(strategy_id)
    except (ValueError, FileNotFoundError):
        return jsonify({"error": "Strategy not found"}), 404
    if request.method == "GET":
        return jsonify(strategy_view(strategy))
    if request.method == "DELETE":
        strategy_path(strategy_id).unlink()
        return jsonify({"deleted": strategy_id})
    body = request.get_json() or {}
    try:
        fields = validate_strategy_body(body, existing=strategy)
    except (ValueError, TypeError, KeyError) as error:
        return jsonify({"error": str(error)}), 400
    return jsonify(strategy_view(save_strategy({**strategy, **fields})))


@studio.post("/strategies/<strategy_id>/update")
def strategy_update(strategy_id):
    """更新到最新: recompute every member factor on the latest data, then backtest the strategy from its evidence
    start (or the given start) to the last day of market data, and append the run to its history."""
    try:
        strategy = load_strategy(strategy_id)
    except (ValueError, FileNotFoundError):
        return jsonify({"error": "Strategy not found"}), 404
    body = request.get_json() or {}
    refreshed, failures = [], []
    if body.get("refresh", True):
        for f in strategy["factors"]:
            if f.get("kind", "factor") != "factor":
                continue
            try:
                original = Path(resolve_factor_paths(f["trace"], f["loop_id"], [{"name": f["name"], "weight": 1}], prefer_refreshed=False)[0]["path"])
                code_path = original / "factor.py"
                if not code_path.is_file():
                    raise ValueError("no factor.py")
                out = refresh_dir(f["trace"], f["loop_id"], f["name"])
                for stale in out.glob("studio_analysis.*.json"):
                    stale.unlink()
                run_refresh(code_path, f["name"], out)
                refreshed.append(f["name"])
            except (ValueError, RuntimeError, subprocess.TimeoutExpired) as error:
                failures.append(f"{f['name']}: {error}")
    try:
        end = str(body.get("end") or "")
        if not end:
            calendar = (Path(os.environ.get("QLIB_PROVIDER_URI", "~/.qlib/qlib_data/cn_data")).expanduser() / "calendars" / "day.txt")
            end = calendar.read_text().strip().splitlines()[-1]
        start = str(body.get("start") or (strategy.get("evidence") or {}).get("start") or "")
        if not start:
            raise ValueError("No start date: pass one or save the strategy with its evidence window")
        request_body = {"factors": strategy["factors"], "model": strategy["model"], **strategy["params"], "start": start, "end": end}
        config = prepare_backtest_config(request_body)
        job_id = launch_backtest(config)
    except (ValueError, TypeError, KeyError) as error:
        return jsonify({"error": str(error), "refreshed": refreshed, "failures": failures}), 400
    except OSError as error:
        return jsonify({"error": str(error), "refreshed": refreshed, "failures": failures}), 500
    strategy.setdefault("runs", []).append({"backtest_id": job_id, "kind": "update"})
    save_strategy(strategy)
    return jsonify({"backtest_id": job_id, "refreshed": refreshed, "failures": failures, "start": start, "end": end}), 202


def signal_export(strategy):
    """Target holdings and the latest ranking from the strategy's newest completed run, as rows for CSV/JSON.

    The holdings are the book TopkDropoutStrategy ends the run with, i.e. what it would hold going into the
    next trading day; the scores are the last signal day's ranking that the next rebalance will read.
    """
    for entry in reversed(strategy.get("runs", [])):
        try:
            folder = job_folder(entry["backtest_id"])
        except ValueError:
            continue
        if not (folder / "result.json").is_file():
            continue
        result = json.loads((folder / "result.json").read_text())
        if result.get("status") != "completed":
            continue
        config = json.loads((folder / "config.json").read_text())
        holdings = result.get("holdings") or {}
        signal = result.get("latest_signal") or {}
        rows = []
        for row in holdings.get("positions", []):
            rows.append({"date": signal.get("date") or config.get("end"), "type": "holding", "instrument": row["instrument"], "weight": row.get("weight"),
                         "amount": row.get("amount"), "price": row.get("price"), "value": row.get("value"), "score": None, "rank": None})
        held = {row["instrument"] for row in holdings.get("positions", [])}
        for row in signal.get("scores", []):
            rows.append({"date": signal.get("date"), "type": "score", "instrument": row["instrument"], "weight": None, "amount": None, "price": None,
                         "value": None, "score": row["score"], "rank": row["rank"], "held": row["instrument"] in held})
        return {"strategy": strategy["name"], "strategy_id": strategy["id"], "backtest_id": entry["backtest_id"],
                "as_of": signal.get("date") or config.get("end"), "market": config.get("market"), "topk": config.get("topk"), "n_drop": config.get("n_drop"),
                "cash": holdings.get("cash"), "total": holdings.get("total"), "rows": rows}
    raise ValueError("这个策略还没有跑完的回测；先点“更新到最新”")


@studio.get("/strategies/<strategy_id>/signal")
def strategy_signal(strategy_id):
    """?format=csv for the file execution systems read; JSON otherwise."""
    try:
        strategy = load_strategy(strategy_id)
    except (ValueError, FileNotFoundError):
        return jsonify({"error": "Strategy not found"}), 404
    try:
        payload = signal_export(strategy)
    except ValueError as error:
        return jsonify({"error": str(error)}), 409
    if request.args.get("format") != "csv":
        return jsonify(payload)
    import csv
    import io

    buffer = io.StringIO()
    names = instrument_names()["names"]
    fields = ["date", "type", "instrument", "name", "weight", "amount", "price", "value", "score", "rank", "held"]
    writer = csv.DictWriter(buffer, fieldnames=fields, extrasaction="ignore")
    writer.writeheader()
    for row in payload["rows"]:
        row = {**row, "name": (names.get(row["instrument"]) or {}).get("name", "")}
        writer.writerow({k: ("" if row.get(k) is None else row.get(k)) for k in fields})
    from urllib.parse import quote

    # Header values must be latin-1: ASCII fallback plus the RFC 5987 percent-encoded UTF-8 name.
    filename = f"signal-{payload['as_of']}-{strategy['name']}.csv".replace("/", "_")
    disposition = f"attachment; filename=\"signal-{payload['as_of']}.csv\"; filename*=UTF-8''{quote(filename)}"
    return Response(buffer.getvalue(), mimetype="text/csv", headers={"Content-Disposition": disposition})


def instrument_names():
    """The code → {name, industry} map from studio_data/instrument_names.json, or an empty map."""
    if not INSTRUMENT_NAMES.is_file():
        return {"source": None, "names": {}}
    try:
        data = json.loads(INSTRUMENT_NAMES.read_text())
    except ValueError:
        return {"source": None, "names": {}}
    return {"source": data.get("source"), "names": data.get("names") or {}}


@studio.get("/instruments/names")
def instruments_names():
    return jsonify(instrument_names())
