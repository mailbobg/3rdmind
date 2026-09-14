"""Local, persisted backtest jobs. Registered under the existing server's auth gate."""
import json
import os
import subprocess
import sys
import uuid
from pathlib import Path

from flask import Blueprint, jsonify, request
from rdagent.log.ui.conf import UI_SETTING
from rdagent.log.server.studio_worker import validate_config, write_json

studio = Blueprint("studio", __name__, url_prefix="/studio")
PROCESSES = {}
ROOT = Path(UI_SETTING.trace_folder).resolve() / "studio_backtests"
TRACE_ROOT = Path(UI_SETTING.trace_folder).resolve()


def job_folder(job_id):
    uuid.UUID(job_id)
    return ROOT / job_id


def research_report_path(report_id):
    path = (TRACE_ROOT / report_id / "research-report.json").resolve()
    if TRACE_ROOT not in path.parents:
        raise ValueError("Invalid research report ID")
    return path


def load_research_report(path):
    report = json.loads(path.read_text())
    workspace = Path(report.get("workspace", ""))
    chart_path = workspace / "ret.parquet"
    if chart_path.is_file():
        import pandas as pd

        frame = pd.read_parquet(chart_path)
        daily = (frame["return"].fillna(0) - frame["cost"].fillna(0)).astype(float)
        equity = (1 + daily).cumprod()
        benchmark = (1 + frame["bench"].fillna(0).astype(float)).cumprod()
        drawdown = equity / equity.cummax() - 1
        report["rows"] = [
            {
                "date": str(index.date()),
                "equity": float(equity.loc[index]),
                "benchmark": float(benchmark.loc[index]),
                "drawdown": float(drawdown.loc[index]),
            }
            for index in frame.index
        ]
    published_expressions = {
        "STR_5": "-Log($close / Ref($close, 5))",
        "RVOL_20": "Std(Log($close / Ref($close, 1)), 20)",
        "VOLSURGE_5_20": "Log((Mean($volume, 5) + 1e-12) / (Mean($volume, 20) + 1e-12))",
    }
    factors = []
    for factor_path in report.get("factor_workspaces", []):
        source = Path(factor_path) / "factor.py"
        if not source.is_file():
            continue
        code = source.read_text()
        name_match = __import__("re").search(r"calculate_([A-Za-z0-9_]+)", code)
        factor_name = name_match.group(1) if name_match else source.parent.name
        factors.append(
            {
                "name": factor_name,
                "file": str(source),
                "code": code,
                "expression": published_expressions.get(factor_name),
                "expression_note": "Qlib expression edition for independent portfolio backtests.",
            }
        )
    report["factors"] = factors
    report["id"] = path.parent.relative_to(TRACE_ROOT).as_posix()
    report["status"] = "completed" if report.get("execution_success") else "failed"
    report.setdefault("model", os.environ.get("LITELLM_CHAT_MODEL", os.environ.get("CHAT_MODEL", "")))
    report.setdefault("dataset", "CSI300")
    report.setdefault(
        "periods",
        {
            "train": [os.environ.get("QLIB_FACTOR_TRAIN_START"), os.environ.get("QLIB_FACTOR_TRAIN_END")],
            "valid": [os.environ.get("QLIB_FACTOR_VALID_START"), os.environ.get("QLIB_FACTOR_VALID_END")],
            "test": [os.environ.get("QLIB_FACTOR_TEST_START"), os.environ.get("QLIB_FACTOR_TEST_END")],
        },
    )
    return report


@studio.get("/research-reports")
def research_reports():
    reports = []
    for path in sorted(
        TRACE_ROOT.glob("*/*/research-report.json"),
        key=lambda item: item.stat().st_mtime,
        reverse=True,
    ):
        report = json.loads(path.read_text())
        reports.append(
            {
                "id": path.parent.relative_to(TRACE_ROOT).as_posix(),
                "status": "completed" if report.get("execution_success") else "failed",
            }
        )
    return jsonify(reports)


@studio.get("/research-reports/<path:report_id>")
def research_report(report_id):
    try:
        path = research_report_path(report_id)
    except ValueError as error:
        return jsonify({"error": str(error)}), 400
    if not path.is_file():
        return jsonify({"error": "Research report not found"}), 404
    return jsonify(load_research_report(path))


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


@studio.route("/backtests", methods=["GET", "POST"])
def backtests():
    ROOT.mkdir(parents=True, exist_ok=True)
    if request.method == "GET":
        jobs = []
        for path in sorted(ROOT.glob("*/config.json"), key=lambda p: p.stat().st_mtime, reverse=True)[:100]:
            result_path = path.parent / "result.json"
            result = json.loads(result_path.read_text()) if result_path.exists() else {"status": "queued"}
            jobs.append({"id": path.parent.name, "config": json.loads(path.read_text()),
                         "status": result["status"]})
        return jsonify(jobs)
    try:
        config = validate_config(request.get_json() or {})
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
