import json
from pathlib import Path

import pandas as pd
import pytest

import rdagent.log.server.app as server
from rdagent.core.experiment import Experiment, FBWorkspace, Task
from rdagent.log.server import studio as studio_module
from rdagent.log.server.studio_worker import (
    load_factor_frame,
    require_signal_coverage,
    trading_day_on_or_before,
    validate_config,
)
from rdagent.log.ui.storage import WebStorage


class _FactorTask(Task):
    def __init__(self, name: str) -> None:
        super().__init__(name=name, description="")
        self.factor_name = name

    def get_task_information(self) -> str:
        return self.name


class _ModelTask(Task):
    def get_task_information(self) -> str:
        return self.name


def _experiment_with_workspaces(tmp_path: Path) -> Experiment:
    tasks = [_FactorTask("STR_5"), _FactorTask("RVOL_20")]
    exp = Experiment(sub_tasks=tasks)
    exp.experiment_workspace = FBWorkspace()
    exp.experiment_workspace.workspace_path = tmp_path / "exp"
    for index, task in enumerate(tasks):
        ws = FBWorkspace(target_task=task)
        ws.workspace_path = tmp_path / f"factor{index}"
        exp.sub_workspace_list[index] = ws
    exp.result = pd.Series({"IC": 0.01})
    return exp


@pytest.mark.offline
def test_metric_event_carries_workspaces(tmp_path: Path) -> None:
    exp = _experiment_with_workspaces(tmp_path)
    data = WebStorage(port=1, path=tmp_path)._obj_to_json(
        obj=exp, tag="Loop_0.running", id="trace", timestamp="2026-09-14T00:00:00"
    )
    content = data["msg"]["content"]
    assert data["msg"]["tag"] == "feedback.metric"
    assert json.loads(content["result"]) == {"IC": 0.01}
    assert content["workspaces"] == {
        "experiment": str(tmp_path / "exp"),
        "factors": [
            {"name": "STR_5", "path": str(tmp_path / "factor0")},
            {"name": "RVOL_20", "path": str(tmp_path / "factor1")},
        ],
    }


@pytest.mark.offline
def test_metric_event_without_sub_workspaces(tmp_path: Path) -> None:
    exp = Experiment(sub_tasks=[])
    exp.result = pd.Series({"IC": 0.0})
    data = WebStorage(port=1, path=tmp_path)._obj_to_json(
        obj=exp, tag="Loop_0.running", id="trace", timestamp="2026-09-14T00:00:00"
    )
    assert data["msg"]["content"]["workspaces"] == {"experiment": None, "factors": []}


def _config(**overrides):
    base = {
        "start": "2025-01-01", "end": "2025-06-30", "market": "csi300",
        "topk": 10, "n_drop": 2, "account": 1000000, "open_cost": 0.0005, "close_cost": 0.0015,
        "factors": [{"name": "STR_5", "path": "/tmp/f0", "weight": 1}],
    }
    base.update(overrides)
    return base


@pytest.mark.offline
def test_validate_config_requires_named_paths() -> None:
    assert validate_config(_config())["factors"][0]["path"] == "/tmp/f0"
    for factors in (
        [{"name": "", "path": "/tmp/f0", "weight": 1}],
        [{"name": "STR_5", "path": "", "weight": 1}],
        [{"name": "STR_5", "expression": "$close", "weight": 1}],
        [{"name": "STR_5", "path": "/tmp/f0", "weight": 0}],
    ):
        with pytest.raises(ValueError):
            validate_config(_config(factors=factors))


@pytest.mark.offline
def test_load_factor_frame_reads_first_column(tmp_path: Path) -> None:
    index = pd.MultiIndex.from_tuples(
        [(pd.Timestamp("2025-01-02"), "SH600000"), (pd.Timestamp("2025-01-03"), "SH600000")],
        names=["datetime", "instrument"],
    )
    pd.DataFrame({"anything": [0.1, 0.2]}, index=index).to_hdf(tmp_path / "result.h5", key="data")
    frame = load_factor_frame({"name": "STR_5", "path": str(tmp_path)}, pd.Timestamp("2025-01-03"), "2025-12-31")
    assert list(frame.columns) == ["STR_5"]
    assert frame.index.get_level_values("datetime").min() == pd.Timestamp("2025-01-03")


@pytest.mark.offline
def test_read_result_takes_the_first_dataset_of_a_multi_key_file(tmp_path: Path) -> None:
    from rdagent.log.server.studio_worker import read_result

    index = pd.MultiIndex.from_tuples([(pd.Timestamp("2025-01-02"), "AAPL")], names=["datetime", "instrument"])
    path = tmp_path / "result.h5"
    pd.DataFrame({"F": [0.5]}, index=index).to_hdf(path, key="data")
    pd.DataFrame({"F": [0.9]}, index=index).to_hdf(path, key="second")
    with pytest.raises(ValueError):
        pd.read_hdf(path)
    assert float(read_result(path).iloc[0, 0]) == 0.5
    assert load_factor_frame({"name": "F", "path": str(tmp_path)}, pd.Timestamp("2025-01-01"), "2025-12-31").iloc[0, 0] == 0.5


@pytest.mark.offline
def test_load_factor_frame_rejects_missing_file(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="result.h5"):
        load_factor_frame({"name": "X", "path": str(tmp_path)}, pd.Timestamp("2025-01-01"), "2025-12-31")


def _task_with_metric(trace_folder: Path, trace_id: str, factor_dir: Path):
    task = server._get_or_create_task(str(trace_folder / trace_id))
    task.messages = [
        {"tag": "research.hypothesis", "loop_id": 0, "timestamp": "t", "content": {"hypothesis": "h"}},
        {
            "tag": "feedback.metric", "loop_id": "0", "timestamp": "t",
            "content": {
                "result": json.dumps({"IC": 0.01, "Rank IC": 0.02}),
                "workspaces": {"experiment": str(factor_dir / "exp"),
                               "factors": [{"name": "STR_5", "path": str(factor_dir / "f0")}]},
            },
        },
    ]
    return task


@pytest.fixture
def studio_client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    trace_folder = tmp_path / "traces"
    workspace_root = tmp_path / "ws"
    (workspace_root / "f0").mkdir(parents=True)
    (workspace_root / "f0" / "result.h5").write_bytes(b"")
    monkeypatch.setattr(server, "log_folder_path", trace_folder)
    monkeypatch.setitem(server.app.config, "LOG_FOLDER_PATH", trace_folder)
    monkeypatch.setattr(studio_module, "TRACE_ROOT", trace_folder)
    monkeypatch.setattr(studio_module, "ROOT", trace_folder / "studio_backtests")
    monkeypatch.setattr(studio_module, "REFRESH_ROOT", trace_folder / "studio_refresh")
    monkeypatch.setattr(studio_module, "STRATEGY_ROOT", trace_folder / "studio_strategies")
    monkeypatch.setattr(studio_module, "INSTRUMENT_NAMES", trace_folder / "studio_data" / "instrument_names.json")
    monkeypatch.setattr(studio_module, "LATEST_DATA", trace_folder / "studio_data" / "daily_pv_latest.h5")
    monkeypatch.setattr(studio_module, "WORKSPACE_ROOT", workspace_root)
    monkeypatch.setattr(studio_module.studio_llm, "_settings_path", trace_folder / "studio_data" / "llm.json")
    monkeypatch.setattr(studio_module.subprocess, "Popen", lambda *a, **k: type("P", (), {"poll": lambda self: None})())
    server.rdagent_processes.clear()
    studio_module.studio_jobs.reset()
    _task_with_metric(trace_folder, "Finance Data Building/demo", workspace_root)
    return server.app.test_client()


def wait_job(client, job_id: str, timeout: float = 5.0) -> dict:
    """Poll /studio/jobs/<id> until the job finishes (tests run the work on a thread with fakes)."""
    import time

    deadline = time.time() + timeout
    while time.time() < deadline:
        job = client.get(f"/studio/jobs/{job_id}").get_json()
        if job["status"] in ("completed", "failed"):
            return job
        time.sleep(0.02)
    raise AssertionError(f"job {job_id} did not finish: {job}")


@pytest.mark.offline
def test_experiments_summarise_loaded_traces(studio_client) -> None:
    trace_folder = server.app.config["LOG_FOLDER_PATH"]
    task = server._get_or_create_task(str(trace_folder / "Finance Data Building/second"))
    task.messages = [
        {"tag": "research.hypothesis", "loop_id": "0", "timestamp": "2026-09-01T10:00:00", "content": {"hypothesis": "first"}},
        {"tag": "feedback.hypothesis_feedback", "loop_id": "0", "timestamp": "2026-09-01T11:00:00", "content": {"decision": True}},
        {"tag": "research.hypothesis", "loop_id": "1", "timestamp": "2026-09-02T10:00:00", "content": {"hypothesis": "second"}},
        {"tag": "feedback.hypothesis_feedback", "loop_id": "1", "timestamp": "2026-09-02T11:00:00", "content": {"decision": False}},
        {"tag": "END", "loop_id": "1", "timestamp": "2026-09-02T12:00:00", "content": {"end_code": 0}},
    ]
    rows = {r["id"]: r for r in studio_client.get("/studio/experiments").get_json()}
    assert rows["Finance Data Building/second"] == {
        "id": "Finance Data Building/second", "scenario": "Finance Data Building", "rounds": 2, "accepted": 1, "market": "csi300", "waiting": None, "confirm": {"mode": "hypothesis", "timeout_min": 30, "instruction": ""}, "auto_answered": 0,
        "status": "completed", "updated": "2026-09-02T11:00:00", "hypothesis": "second", "messages": 5,
    }
    # The demo trace has events but no END and no live process: it ended without reporting.
    assert rows["Finance Data Building/demo"]["status"] == "ended"
    assert rows["Finance Data Building/demo"]["rounds"] == 1


@pytest.mark.offline
def test_prediction_coverage_reads_pred_pkl(studio_client, tmp_path: Path) -> None:
    import pandas as pd

    artifacts = tmp_path / "ws" / "exp" / "mlruns" / "0" / "run" / "artifacts"
    artifacts.mkdir(parents=True)
    index = pd.MultiIndex.from_product([pd.to_datetime(["2025-01-02", "2025-01-03", "2025-06-30"]), ["SH600000", "SZ000001"]],
                                       names=["datetime", "instrument"])
    pd.Series(range(6), index=index, name="score").to_pickle(artifacts / "pred.pkl")
    response = studio_client.get("/studio/predictions/coverage", query_string={"trace": "Finance Data Building/demo", "loop_id": "0"})
    assert response.status_code == 200
    assert response.get_json() == {"start": "2025-01-02", "end": "2025-06-30", "days": 3, "rows": 6}
    missing = studio_client.get("/studio/predictions/coverage", query_string={"trace": "Finance Data Building/demo", "loop_id": "7"})
    assert missing.status_code == 400


@pytest.mark.offline
def test_factor_coverage_reads_result_h5(studio_client, tmp_path: Path) -> None:
    import pandas as pd

    index = pd.MultiIndex.from_product([pd.to_datetime(["2022-10-10", "2025-12-31"]), ["SH600000"]], names=["datetime", "instrument"])
    pd.DataFrame({"STR_5": [1.0, 2.0]}, index=index).to_hdf(tmp_path / "ws" / "f0" / "result.h5", key="data")
    response = studio_client.get("/studio/factors/coverage", query_string={"trace": "Finance Data Building/demo", "loop_id": "0", "name": "STR_5"})
    assert response.status_code == 200
    assert response.get_json() == {"start": "2022-10-10", "end": "2025-12-31", "days": 2, "rows": 2}
    assert studio_client.get("/studio/factors/coverage", query_string={"trace": "Finance Data Building/demo", "loop_id": "0", "name": "nope"}).status_code == 400


@pytest.mark.offline
def test_refresh_replaces_the_signal_source(studio_client, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A recomputed factor is what the library, coverage and backtests read afterwards."""
    import pandas as pd

    (tmp_path / "ws" / "f0" / "factor.py").write_text("print('factor')")

    def fake_refresh(code_path: Path, name: str, out_dir: Path, market: str = "csi300"):
        assert Path(code_path).read_text() == "print('factor')"
        index = pd.MultiIndex.from_product([pd.to_datetime(["2022-10-10", "2026-09-11"]), ["SH600000"]], names=["datetime", "instrument"])
        out_dir.mkdir(parents=True, exist_ok=True)
        pd.DataFrame({name: [1.0, 2.0]}, index=index).to_hdf(out_dir / "result.h5", key="data", mode="w")
        meta = {"name": name, "start": "2022-10-10", "end": "2026-09-11", "rows": 2, "computed_at": "now",
                "data": {"start": "2022-10-10", "end": "2026-09-11", "rows": 2}}
        (out_dir / "meta.json").write_text(json.dumps(meta))
        return {"status": "completed", **meta}

    monkeypatch.setattr(studio_module, "run_refresh", fake_refresh)
    ref = {"trace": "Finance Data Building/demo", "loop_id": 0, "name": "STR_5"}
    response = studio_client.post("/studio/factors/refresh", json=ref)
    assert response.status_code == 202, response.get_json()
    job = wait_job(studio_client, response.get_json()["job"])
    assert job["status"] == "completed" and job["kind"] == "refresh" and job["result"]["end"] == "2026-09-11"
    # Listed among the jobs, with its market and where it belongs.
    listed = next(j for j in studio_client.get("/studio/jobs").get_json()["items"] if j["id"] == job["id"])
    assert listed["link"]["name"] == "STR_5" and listed["market"] == "csi300"

    entry = next(f for f in studio_client.get("/studio/factors").get_json() if f["name"] == "STR_5")
    assert entry["refreshed"]["end"] == "2026-09-11"
    assert entry["coverage"] == {"start": "2022-10-10", "end": "2026-09-11"}
    coverage = studio_client.get("/studio/factors/coverage", query_string={**ref, "loop_id": "0"}).get_json()
    assert coverage["end"] == "2026-09-11"
    with server.app.app_context():
        resolved = studio_module.resolve_factor_paths(ref["trace"], 0, [{"name": "STR_5", "weight": 1}])
        assert Path(resolved[0]["path"]) == studio_module.refresh_dir(ref["trace"], 0, "STR_5")
        original = studio_module.resolve_factor_paths(ref["trace"], 0, [{"name": "STR_5", "weight": 1}], prefer_refreshed=False)
        assert Path(original[0]["path"]) == tmp_path / "ws" / "f0"


@pytest.mark.offline
def test_recorded_loops_counts_started_and_finished_rounds() -> None:
    msgs = [
        {"tag": "research.hypothesis", "loop_id": "0"}, {"tag": "feedback.hypothesis_feedback", "loop_id": "0"},
        {"tag": "research.hypothesis", "loop_id": "1"}, {"tag": "feedback.hypothesis_feedback", "loop_id": 1},
        {"tag": "research.hypothesis", "loop_id": "2"},
    ]
    assert server.recorded_loops(msgs) == (3, False)
    assert server.recorded_loops(msgs[:4]) == (2, True)
    assert server.recorded_loops([]) == (0, True)


@pytest.mark.offline
def test_resume_appends_to_the_same_trace(studio_client, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """/resume restores the loop in place: same registry key, history kept, END dropped, loop_n = done + asked."""
    trace_folder = server.app.config["LOG_FOLDER_PATH"]
    trace_dir = trace_folder / "Finance Data Building/demo"
    (trace_dir / "__session__" / "0").mkdir(parents=True)
    previous = server.rdagent_processes[str(trace_dir)]
    previous.messages = [
        {"tag": "research.hypothesis", "loop_id": "0", "content": {"hypothesis": "h"}},
        {"tag": "feedback.hypothesis_feedback", "loop_id": "0", "content": {"decision": True}},
        {"tag": "END", "content": {"end_code": 0}},
    ]
    started = []
    monkeypatch.setattr(server.RDAgentTask, "start", lambda self: started.append(self))
    response = studio_client.post("/resume", json={"id": "Finance Data Building/demo", "loops": 2})
    assert response.status_code == 200, response.get_json()
    assert response.get_json() == {"id": "Finance Data Building/demo", "loops": 2, "loop_n": 3}
    task = server.rdagent_processes[str(trace_dir)]
    assert task is started[0] and task.target_name == "resume"
    assert task.kwargs == {"scenario": "Finance Data Building", "path": str(trace_dir), "loop_n": 3, "all_duration": None}
    assert [m["tag"] for m in task.messages] == ["research.hypothesis", "feedback.hypothesis_feedback"]
    # The continued run keeps the trace's universe (csi300 here: no studio-run.json), not Qlib's defaults.
    assert task.env["QLIB_FACTOR_MARKET"] == task.env["QLIB_MODEL_MARKET"] == "csi300" and task.env["QLIB_QUANT_BENCHMARK"] == "SH000300"
    # Guards: unknown scenario, missing session, bad loop count.
    assert studio_client.post("/resume", json={"id": "General Model Implementation/x", "loops": 1}).status_code == 400
    assert studio_client.post("/resume", json={"id": "Finance Data Building/nosession", "loops": 1}).status_code == 404
    assert studio_client.post("/resume", json={"id": "Finance Data Building/demo", "loops": 0}).status_code == 400


@pytest.mark.offline
def test_combine_drops_incomplete_rows_only_for_the_columns_it_uses() -> None:
    import numpy as np
    import pandas as pd
    from rdagent.log.server.studio_worker import combine, singles_failure

    days = pd.to_datetime(["2025-01-02", "2025-01-03", "2025-01-06"])
    index = pd.MultiIndex.from_product([days, ["A", "B", "C"]], names=["datetime", "instrument"])
    ranks = pd.DataFrame({"long": np.tile([0.2, 0.5, 0.8], 3), "short": np.r_[np.tile([0.8, 0.5, 0.2], 2), [np.nan] * 3]}, index=index)
    prepared = {"ranks": ranks, "label": None, "prior_day": days[0], "end_day": days[-1], "calendar": days}
    model = {"method": "rank"}
    alone, _ = combine(prepared, ["long"], [1.0], model, log=lambda *_: None)
    assert alone.index.get_level_values("datetime").nunique() == 3   # the long factor is not cut by the short one
    with pytest.raises(ValueError):                                   # the pair only covers two days, short of the window
        combine(prepared, ["long", "short"], [1.0, 1.0], model, log=lambda *_: None)
    prepared["end_day"] = days[1]
    both, _ = combine(prepared, ["long", "short"], [1.0, 1.0], model, log=lambda *_: None)
    assert both.index.get_level_values("datetime").nunique() == 2 and both.loc[(days[0], "A")] == pytest.approx(0.5)
    message = singles_failure({"F1": {"error": "signal ends 2025-12-31"}, "F2": {"error": "signal ends 2025-12-31"}, "F3": {"error": "no rows"}})
    assert message.startswith("No candidate could be backtested alone") and "F1、F2：signal ends 2025-12-31" in message and "F3：no rows" in message


@pytest.mark.offline
def test_signal_diagnosis_scores_each_signal_on_the_window() -> None:
    import pandas as pd
    from rdagent.log.server import studio_worker as worker

    days = pd.to_datetime(["2025-01-02", "2025-01-03", "2025-01-06"])
    index = pd.MultiIndex.from_product([days, ["A", "B", "C", "D"]], names=["datetime", "instrument"])
    good = pd.Series([0.1, 0.2, 0.3, 0.4] * 3, index=index)          # aligned with the label
    bad = pd.Series([0.4, 0.3, 0.2, 0.1] * 3, index=index)           # points the other way
    label = pd.Series([-1.0, -0.3, 0.3, 1.0] * 3, index=index)
    ranks = pd.concat([good.rename("good"), bad.rename("bad")], axis=1)
    prepared = {"ranks": ranks, "label": label, "prior_day": days[0],
                "factors": [{"name": "good", "weight": 1}, {"name": "bad", "weight": 1}]}
    score = (good - bad) / 2
    out = worker.signal_diagnosis(prepared, score)
    by_name = {s["name"]: s for s in out["signals"]}
    assert by_name["good"]["rank_ic"] == pytest.approx(1.0) and by_name["bad"]["rank_ic"] == pytest.approx(-1.0)
    assert by_name["good"]["corr_with_score"] == pytest.approx(1.0) and by_name["bad"]["corr_with_score"] == pytest.approx(-1.0)
    assert out["correlation"]["names"] == ["good", "bad"]
    assert out["correlation"]["matrix"][0][1] == pytest.approx(-1.0)
    assert out["correlation"]["days"] == 3


@pytest.mark.offline
def test_summarize_report_compounds_net_returns() -> None:
    import pandas as pd
    from rdagent.log.server import studio_worker as worker

    report = pd.DataFrame({"return": [0.01, -0.02, 0.03], "cost": [0.001, 0.001, 0.001], "bench": [0.0, 0.01, 0.0],
                           "turnover": [0.5, 0.5, 0.5], "account": [1e6, 1e6, 1e6]}, index=pd.to_datetime(["2025-01-02", "2025-01-03", "2025-01-06"]))
    metrics, rows = worker.summarize_report(report)
    assert metrics["total_return"] == pytest.approx((1.009 * 0.979 * 1.029) - 1)
    assert metrics["benchmark_return"] == pytest.approx(0.01)
    assert metrics["days"] == 3 and len(rows) == 3 and rows[-1]["date"] == "2025-01-06"


@pytest.mark.offline
def test_diagnose_route_starts_a_worker_for_completed_multi_signal_jobs(studio_client, tmp_path: Path) -> None:
    folder = studio_module.ROOT / "11111111-1111-1111-1111-111111111111"
    folder.mkdir(parents=True)
    write = studio_module.write_json
    write(folder / "config.json", {"factors": [{"name": "a"}, {"name": "b"}]})
    write(folder / "result.json", {"status": "running"})
    assert studio_client.post("/studio/backtests/11111111-1111-1111-1111-111111111111/diagnose").status_code == 409
    write(folder / "result.json", {"status": "completed"})
    response = studio_client.post("/studio/backtests/11111111-1111-1111-1111-111111111111/diagnose")
    assert response.status_code == 202
    assert json.loads((folder / "diagnosis.json").read_text()) == {"status": "queued"}
    assert studio_client.get("/studio/backtests/11111111-1111-1111-1111-111111111111").get_json()["breakdown"] == {"status": "queued"}
    write(folder / "config.json", {"factors": [{"name": "a"}]})
    assert studio_client.post("/studio/backtests/11111111-1111-1111-1111-111111111111/diagnose").status_code == 400


@pytest.mark.offline
def test_split_window_keeps_a_validation_tail() -> None:
    import pandas as pd
    from rdagent.log.server.studio_worker import split_window

    calendar = pd.bdate_range("2025-01-01", periods=300)
    search, valid = split_window(calendar, "2025-01-01", str(calendar[-1].date()), 2 / 3)
    assert search[0] == "2025-01-01" and valid[1] == str(calendar[-1].date())
    assert pd.Timestamp(search[1]) < pd.Timestamp(valid[0])
    assert (calendar <= pd.Timestamp(search[1])).sum() == 200
    with pytest.raises(ValueError):
        split_window(calendar, "2025-01-01", str(calendar[30].date()), 2 / 3)


@pytest.mark.offline
def test_validate_config_checks_the_search_block() -> None:
    assert validate_config(_config(search={}))["search"] == {"objective": "sharpe", "split": pytest.approx(2 / 3)}
    assert validate_config(_config(search={"objective": "total_return", "split": 0.5}))["search"]["objective"] == "total_return"
    with pytest.raises(ValueError):
        validate_config(_config(search={"objective": "alpha"}))
    with pytest.raises(ValueError):
        validate_config(_config(search={"split": 0.95}))
    assert "search" not in validate_config(_config())


@pytest.mark.offline
def test_search_routes_start_and_list_jobs(studio_client, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(studio_module, "SEARCH_ROOT", tmp_path / "traces" / "studio_searches")
    (tmp_path / "ws" / "f1").mkdir(parents=True)
    (tmp_path / "ws" / "f1" / "result.h5").write_bytes(b"")
    task = server.rdagent_processes[str(tmp_path / "traces" / "Finance Data Building/demo")]
    task.messages[1]["content"]["workspaces"]["factors"].append({"name": "RVOL_20", "path": str(tmp_path / "ws" / "f1")})
    body = {"factors": [{"name": "STR_5", "weight": 1, "trace": "Finance Data Building/demo", "loop_id": 0},
                        {"name": "RVOL_20", "weight": -1, "trace": "Finance Data Building/demo", "loop_id": 0}],
            "start": "2025-01-01", "end": "2025-06-30", "market": "csi300", "benchmark": "SH000300",
            "topk": 10, "n_drop": 2, "account": 1000000, "open_cost": 0.0005, "close_cost": 0.0015,
            "search": {"objective": "total_return"}}
    response = studio_client.post("/studio/searches", json=body)
    assert response.status_code == 202, response.get_json()
    job_id = response.get_json()["id"]
    listed = studio_client.get("/studio/searches").get_json()
    assert [j["id"] for j in listed] == [job_id] and listed[0]["status"] == "queued"
    detail = studio_client.get(f"/studio/searches/{job_id}").get_json()
    assert detail["status"] == "queued" and detail["config"]["search"]["objective"] == "total_return"
    assert "path" not in detail["config"]["factors"][0]
    one = dict(body, factors=body["factors"][:1])
    assert studio_client.post("/studio/searches", json=one).status_code == 400


@pytest.mark.offline
def test_search_prefilter_is_on_by_default_and_reports_exclusions(
    studio_client, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import numpy as np

    monkeypatch.setattr(studio_module, "SEARCH_ROOT", tmp_path / "traces" / "studio_searches")
    days = pd.bdate_range("2025-01-01", periods=5)
    stocks = ["A", "B", "C", "D"]
    index = pd.MultiIndex.from_product([days, stocks], names=["datetime", "instrument"])
    rng = np.random.RandomState(0)
    series = {
        "F_A": pd.Series(np.arange(len(index), dtype=float), index=index),
        "F_B": pd.Series(rng.randn(len(index)), index=index),
        "F_DUP": pd.Series(np.arange(len(index), dtype=float) * 2.0, index=index),
        "F_WEAK": pd.Series(rng.randn(len(index)), index=index),
    }
    ws = tmp_path / "ws"
    for name, values in series.items():
        folder = ws / name.lower()
        folder.mkdir(parents=True)
        values.to_frame("x").to_hdf(folder / "result.h5", key="data")

    def cache(name, rank_ic, icir):
        folder = ws / name.lower()
        (folder / "studio_analysis.csi300.json").write_text(json.dumps({
            "status": "completed", "version": studio_module.ANALYSIS_VERSION, "source_mtime": (folder / "result.h5").stat().st_mtime,
            "rank_ic": {"mean": rank_ic, "std": 0.1, "ir": icir, "positive_ratio": 0.6}}))

    cache("F_A", 0.03, 0.5)
    cache("F_B", 0.025, 0.45)
    cache("F_DUP", 0.02, 0.4)
    cache("F_WEAK", 0.001, 0.01)
    task = server.rdagent_processes[str(tmp_path / "traces" / "Finance Data Building/demo")]
    task.messages[1]["content"]["workspaces"]["factors"].extend(
        {"name": name, "path": str(ws / name.lower())} for name in series
    )

    def body(names, **search):
        return {"factors": [{"name": n, "weight": 1, "trace": "Finance Data Building/demo", "loop_id": 0} for n in names],
                "start": "2025-01-01", "end": "2025-06-30", "market": "csi300", "benchmark": "SH000300",
                "topk": 10, "n_drop": 2, "account": 1000000, "open_cost": 0.0005, "close_cost": 0.0015,
                "search": {"objective": "sharpe", **search}}

    # Default: prefilter on. F_WEAK is too weak, F_DUP duplicates F_A; F_A and F_B survive.
    response = studio_client.post("/studio/searches", json=body(["F_A", "F_B", "F_DUP", "F_WEAK"]))
    assert response.status_code == 202, response.get_json()
    detail = studio_client.get(f"/studio/searches/{response.get_json()['id']}").get_json()
    assert sorted(f["name"] for f in detail["config"]["factors"]) == ["F_A", "F_B"]
    prefilter = detail["config"]["search"]["prefilter"]
    assert prefilter["enabled"] is True
    assert sorted(e["name"] for e in prefilter["excluded"]) == ["F_DUP", "F_WEAK"]
    assert any("F_A" in e["reason"] for e in prefilter["excluded"] if e["name"] == "F_DUP")

    # Opt-out: everything is kept.
    response = studio_client.post("/studio/searches", json=body(["F_A", "F_B", "F_DUP", "F_WEAK"], prefilter=False))
    assert response.status_code == 202, response.get_json()
    detail = studio_client.get(f"/studio/searches/{response.get_json()['id']}").get_json()
    assert len(detail["config"]["factors"]) == 4
    assert detail["config"]["search"]["prefilter"] == {"enabled": False, "excluded": [], "flipped": []}

    # Screening down to fewer than two candidates refuses to start, with reasons.
    response = studio_client.post("/studio/searches", json=body(["F_A", "F_DUP", "F_WEAK"]))
    assert response.status_code == 400
    payload = response.get_json()
    assert "F_WEAK" in payload["error"] and [e["name"] for e in payload["prefilter"]["excluded"]]


@pytest.mark.offline
def test_search_preview_reports_kept_and_excluded_without_starting(
    studio_client, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import numpy as np

    monkeypatch.setattr(studio_module, "SEARCH_ROOT", tmp_path / "traces" / "studio_searches")
    days = pd.bdate_range("2025-01-01", periods=5)
    stocks = ["A", "B", "C", "D"]
    index = pd.MultiIndex.from_product([days, stocks], names=["datetime", "instrument"])
    rng = np.random.RandomState(1)
    series = {
        "F_A": pd.Series(rng.randn(len(index)), index=index),
        "F_WEAK": pd.Series(rng.randn(len(index)), index=index),
    }
    ws = tmp_path / "ws"
    for name, values in series.items():
        folder = ws / name.lower()
        folder.mkdir(parents=True)
        values.to_frame("x").to_hdf(folder / "result.h5", key="data")

    def cache(name, rank_ic, icir):
        folder = ws / name.lower()
        (folder / "studio_analysis.csi300.json").write_text(json.dumps({
            "status": "completed", "version": studio_module.ANALYSIS_VERSION, "source_mtime": (folder / "result.h5").stat().st_mtime,
            "rank_ic": {"mean": rank_ic, "std": 0.1, "ir": icir, "positive_ratio": 0.6}}))

    cache("F_A", 0.03, 0.5)
    cache("F_WEAK", 0.001, 0.01)
    task = server.rdagent_processes[str(tmp_path / "traces" / "Finance Data Building/demo")]
    task.messages[1]["content"]["workspaces"]["factors"].extend(
        {"name": name, "path": str(ws / name.lower())} for name in series
    )
    response = studio_client.post("/studio/searches/preview", json={
        "factors": [{"name": n, "weight": 1, "trace": "Finance Data Building/demo", "loop_id": 0} for n in series]})
    assert response.status_code == 200, response.get_json()
    data = response.get_json()
    assert [f["name"] for f in data["kept"]] == ["F_A"]
    assert [e["name"] for e in data["excluded"]] == ["F_WEAK"]
    assert data["excluded"][0]["trace"] == "Finance Data Building/demo"
    # The screen judges like the gate: a recent analysis is read at the horizon where |t| clears its own bar
    # (20-day t 1.8 passes the 1.5 bar although the 1-day t 1.0 would not), the Rank IC size is noted rather
    # than excluding, and a search on another universe says whose numbers were used.
    long_run = {"status": "completed", "version": studio_module.ANALYSIS_VERSION, "source_mtime": (ws / "f_a" / "result.h5").stat().st_mtime,
                "days": 400, "rank_ic": {"mean": 0.004, "ir": 0.05, "t": 1.0, "positive_ratio": 0.5},
                "horizons": [{"days": 1, "residual_rank_ic": {"t": 1.0, "mean": 0.004}}, {"days": 20, "residual_rank_ic": {"t": 1.8, "mean": 0.012}}]}
    (ws / "f_a" / "studio_analysis.csi300.json").write_text(json.dumps(long_run))
    data = studio_client.post("/studio/searches/preview", json={"market": "csi1000",
        "factors": [{"name": "F_A", "weight": 1, "trace": "Finance Data Building/demo", "loop_id": 0}]}).get_json()
    assert data["market"] == "csi1000" and [f["name"] for f in data["kept"]] == ["F_A"]
    note = data["kept"][0]["note"]
    assert "t 1.80（20 日）" in note and "量级不到 0.02" in note and "偏弱" in note and "按 csi300 的数" in note
    assert data["thresholds"]["t_weak"] == {"1": 2.0, "5": 1.75, "10": 1.5, "20": 1.5}
    # Nothing was launched: no job folder appeared.
    assert list((tmp_path / "traces" / "studio_searches").glob("*/config.json")) == []
    assert data["analyzing"] == 0
    # A copy of F_A already computed on csi1000 (a strategy or an earlier search put it there) but not yet
    # analysed there: the screen resolves to the copy, still judges by the own-universe numbers, and queues
    # the copy's analysis on csi1000 so the next screen is exact.
    monkeypatch.setattr(studio_module, "REFRESH_ROOT", tmp_path / "traces" / "studio_refresh")
    copy = studio_module.refresh_dir("Finance Data Building/demo", 0, "F_A", "csi1000")
    copy.mkdir(parents=True)
    series["F_A"].to_frame("x").to_hdf(copy / "result.h5", key="data")
    analysed = []
    monkeypatch.setattr(studio_module, "analyze_factor", lambda workspace, market: analysed.append((Path(workspace), market)))
    monkeypatch.setattr(studio_module.studio_jobs, "run", lambda kind, title, work, **meta: (work({"id": "job-1"}), {"id": "job-1", "kind": kind, **meta})[1])
    monkeypatch.setattr(studio_module.studio_jobs, "update", lambda *a, **k: None)
    monkeypatch.setattr(studio_module.studio_jobs, "list_jobs", lambda **k: [])
    data = studio_client.post("/studio/searches/preview", json={"market": "csi1000",
        "factors": [{"name": "F_A", "weight": 1, "trace": "Finance Data Building/demo", "loop_id": 0}]}).get_json()
    assert [f["name"] for f in data["kept"]] == ["F_A"] and "按 csi300 的数" in data["kept"][0]["note"]
    assert data["analyzing"] == 1 and analysed == [(copy, "csi1000")]
    # An analysis that failed on this very signal (all NaN, nothing inside the universe) is an implementation
    # failure: the screen says so instead of letting the factor through as "not analysed yet", and the
    # background job does not retry it.
    (ws / "f_weak" / "studio_analysis.csi300.json").write_text(json.dumps({
        "status": "failed", "version": studio_module.ANALYSIS_VERSION, "source_mtime": (ws / "f_weak" / "result.h5").stat().st_mtime,
        "error": "factor has no valid values: all 20 rows are NaN"}))
    data = studio_client.post("/studio/searches/preview", json={
        "factors": [{"name": n, "weight": 1, "trace": "Finance Data Building/demo", "loop_id": 0} for n in series]}).get_json()
    assert [e["name"] for e in data["excluded"]] == ["F_WEAK"] and data["excluded"][0]["reason"].startswith("没有产出可用的值（factor has no valid values")
    library = {f["name"]: f for f in studio_client.get("/studio/factors").get_json()}
    assert library["F_WEAK"]["analysis"] is None and library["F_WEAK"]["analysis_error"].startswith("factor has no valid values")
    with server.app.app_context():
        assert "F_WEAK" not in [f["name"] for f in studio_module.pending_analyses("cn")]
    # Without a basket the screen picks from the whole library of the market's region: the strongest few
    # ticked (limit), the rest listed with a reason, and cross-universe copies skipped by the duplicate check.
    data = studio_client.post("/studio/searches/preview", json={"factors": [], "market": "csi300", "limit": 1}).get_json()
    assert [f["name"] for f in data["kept"]] == ["F_A"]
    assert {e["name"]: e["reason"] for e in data["excluded"]}["F_WEAK"].startswith("没有产出可用的值")
    assert studio_client.post("/studio/searches/preview", json={"factors": []}).status_code == 400  # no market either
    task.messages[1]["content"]["workspaces"]["factors"].append({"name": "F_B", "path": str(ws / "f_a")})
    data = studio_client.post("/studio/searches/preview", json={"factors": [], "market": "csi300", "limit": 1}).get_json()
    names = {e["name"]: e["reason"] for e in data["excluded"]}
    assert [f["name"] for f in data["kept"]] == ["F_A"] and "已有 1 个更强的候选" in names["F_B"]


@pytest.mark.offline
def test_prefilter_judges_weakness_by_t_when_the_analysis_has_one(tmp_path: Path) -> None:
    from rdagent.log.server.studio import rank_ic_t

    assert rank_ic_t(None) is None and rank_ic_t({"rank_ic": {"mean": 0.02, "ir": 0.1}}) is None
    assert rank_ic_t({"rank_ic": {"mean": 0.02, "ir": 0.1, "t": 1.7}}) == 1.7
    assert rank_ic_t({"days": 400, "rank_ic": {"mean": 0.02, "ir": 0.1}}) == pytest.approx(0.1 * 20)


@pytest.mark.offline
def test_analyze_pending_runs_one_job_over_the_unanalysed_library(studio_client, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    analysed = []
    monkeypatch.setattr(studio_module, "analyze_factor", lambda workspace, market: analysed.append((workspace.name, market)) or {"status": "completed"})
    monkeypatch.setattr(studio_module.time, "sleep", lambda s: None)
    library = studio_client.get("/studio/factors").get_json()
    pending = [f["name"] for f in library if f["analysis"] is None]
    assert pending, library
    started = studio_client.post("/studio/factors/analyze-pending")
    assert started.status_code == 202, started.get_json()
    payload = started.get_json()
    assert payload["pending"] == len(pending)
    # A second call while it runs (or right after) returns the same job rather than starting another.
    again = studio_client.post("/studio/factors/analyze-pending").get_json()
    job = wait_job(studio_client, payload["job"])
    # Either the same job came back, or the first one had already finished (the fake analysis is instant).
    assert again["job"] in (payload["job"], None) or job["status"] == "completed"
    if again["job"] not in (payload["job"], None):
        wait_job(studio_client, again["job"])
    assert job["status"] == "completed", job
    assert job["kind"] == "factor_analysis" and job["progress"] == {"done": len(pending), "total": len(pending)}
    assert sorted(job["result"]["analyzed"]) == sorted(pending) and job["result"]["failures"] == []
    assert {m for _, m in analysed} == {"csi300"}


@pytest.mark.offline
def test_run_pending_analyses_waits_for_heavier_work_and_keeps_going_past_failures(monkeypatch: pytest.MonkeyPatch) -> None:
    from rdagent.log.server import studio_jobs

    studio_jobs.reset()
    blocker = studio_jobs.create("backtest", "回测", status="running")
    waits = []

    def sleep(seconds):
        waits.append(seconds)
        studio_jobs.finish(blocker["id"])  # the backtest ends while we wait

    calls = []

    def fake_analyze(workspace, market):
        calls.append(workspace.name)
        if workspace.name == "bad":
            raise RuntimeError("no result.h5")
        return {"status": "completed"}

    monkeypatch.setattr(studio_module, "analyze_factor", fake_analyze)
    monkeypatch.setattr(studio_module, "factor_workspace", lambda trace, loop_id, name: Path("/ws") / name)
    job = studio_jobs.create("factor_analysis", "分析", total=2, status="running")
    items = [{"trace": "T/a", "loop_id": 0, "name": "good", "market": "csi300"}, {"trace": "T/a", "loop_id": 0, "name": "bad", "market": "csi300"}]
    result = studio_module.run_pending_analyses(job, items, sleep=sleep)
    assert waits == [15] and calls == ["good", "bad"]
    assert result == {"analyzed": ["good"], "failures": [{"name": "bad", "error": "no result.h5"}]}
    assert studio_jobs.get(job["id"])["progress"] == {"done": 2, "total": 2}


@pytest.mark.offline
def test_validate_config_keeps_the_search_prefilter_block() -> None:
    prefilter = {"enabled": True, "excluded": [{"name": "F_WEAK", "reason": "too weak"}], "flipped": []}
    out = validate_config(_config(search={"prefilter": prefilter}))
    assert out["search"]["prefilter"] == prefilter


@pytest.mark.offline
def test_strategies_are_saved_listed_updated_and_deleted(studio_client, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # Evidence backtest the strategy points at.
    job = studio_module.ROOT / "22222222-2222-2222-2222-222222222222"
    job.mkdir(parents=True)
    studio_module.write_json(job / "config.json", {"start": "2025-01-02", "end": "2025-06-30", "factors": [{"name": "STR_5"}]})
    studio_module.write_json(job / "result.json", {"status": "completed", "metrics": {"total_return": 0.05, "sharpe": 0.5, "max_drawdown": -0.1}})
    body = {"name": "反转一号", "note": "验证通过", "factors": [{"name": "STR_5", "weight": -1, "trace": "Finance Data Building/demo", "loop_id": 0}],
            "model": {"method": "rank"}, "params": {"market": "csi300", "benchmark": "SH000300", "topk": 10, "n_drop": 2, "account": 1000000, "open_cost": 0.0005, "close_cost": 0.0015},
            "evidence": {"backtest_id": "22222222-2222-2222-2222-222222222222", "start": "2025-01-02", "end": "2025-06-30"}}
    created = studio_client.post("/studio/strategies", json=body)
    assert created.status_code == 201, created.get_json()
    strategy = created.get_json()
    assert strategy["factors"][0]["weight"] == -1 and "path" not in strategy["factors"][0]
    assert "horizon" not in strategy["params"] and "rebalance" not in strategy["params"]  # daily setup left implicit
    assert strategy["run_details"][0]["total_return"] == 0.05 and strategy["run_details"][0]["kind"] == "evidence"
    listed = studio_client.get("/studio/strategies").get_json()
    assert listed[0]["name"] == "反转一号" and listed[0]["latest"]["total_return"] == 0.05 and listed[0]["run_count"] == 1
    renamed = studio_client.patch(f"/studio/strategies/{strategy['id']}", json={"name": "反转二号"})
    assert renamed.get_json()["name"] == "反转二号" and renamed.get_json()["factors"] == strategy["factors"]
    assert studio_client.post("/studio/strategies", json={**body, "name": ""}).status_code == 400

    # 更新到最新: no refresh (no factor.py in the fixture), backtest launched from the evidence start to the given end.
    monkeypatch.setattr(studio_module, "run_refresh", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("no qlib here")))
    (tmp_path / "ws" / "f0" / "factor.py").write_text("print(1)")
    updated = studio_client.post(f"/studio/strategies/{strategy['id']}/update", json={"end": "2025-12-31"})
    assert updated.status_code == 202, updated.get_json()
    job = wait_job(studio_client, updated.get_json()["job"])
    assert job["status"] == "completed", job
    payload = job["result"]
    assert payload["start"] == "2025-01-02" and payload["end"] == "2025-12-31" and payload["failures"] and not payload["refreshed"]
    detail = studio_client.get(f"/studio/strategies/{strategy['id']}").get_json()
    assert [r["kind"] for r in detail["run_details"]] == ["evidence", "update"]
    assert detail["run_details"][1]["status"] == "queued" and detail["run_details"][1]["end"] == "2025-12-31"
    # 更新到最新 with its own window: the tracking run takes the given start too.
    windowed = studio_client.post(f"/studio/strategies/{strategy['id']}/update", json={"start": "2025-03-03", "end": "2025-12-31", "refresh": False})
    assert windowed.status_code == 202, windowed.get_json()
    assert wait_job(studio_client, windowed.get_json()["job"])["result"]["start"] == "2025-03-03"
    # Saving another backtest over this strategy replaces its portfolio and evidence and starts tracking over;
    # id, creation time and note survive, the name stays when none is given.
    studio_client.patch(f"/studio/strategies/{strategy['id']}", json={"note": "keep me"})
    replaced = studio_client.post("/studio/strategies", json={**body, "name": "", "note": "", "replace": strategy["id"], "params": {**body["params"], "topk": 5},
                                                              "evidence": {"backtest_id": "22222222-2222-2222-2222-222222222222", "start": "2025-02-03", "end": "2025-06-30"}})
    assert replaced.status_code == 200, replaced.get_json()
    r = replaced.get_json()
    assert r["id"] == strategy["id"] and r["name"] == "反转二号" and r["note"] == "keep me" and r["created"] == strategy["created"]
    assert r["params"]["topk"] == 5 and r["evidence"]["start"] == "2025-02-03" and [x["kind"] for x in r["run_details"]] == ["evidence"]
    assert studio_client.post("/studio/strategies", json={**body, "replace": "00000000-0000-0000-0000-000000000000"}).status_code == 404
    assert studio_client.delete(f"/studio/strategies/{strategy['id']}").status_code == 200
    assert studio_client.get(f"/studio/strategies/{strategy['id']}").status_code == 404


@pytest.mark.offline
def test_latest_scores_ranks_the_last_day() -> None:
    import pandas as pd
    from rdagent.log.server.studio_worker import latest_scores

    index = pd.MultiIndex.from_product([pd.to_datetime(["2025-06-27", "2025-06-30"]), ["A", "B", "C"]], names=["datetime", "instrument"])
    score = pd.Series([0.1, 0.2, 0.3, 0.9, 0.1, 0.5], index=index)
    out = latest_scores(score, topk=1)
    assert out["date"] == "2025-06-30" and out["universe"] == 3
    assert [(r["instrument"], r["rank"]) for r in out["scores"]] == [("A", 1), ("C", 2), ("B", 3)]


@pytest.mark.offline
def test_strategy_signal_exports_holdings_and_scores(studio_client, tmp_path: Path) -> None:
    job = studio_module.ROOT / "33333333-3333-3333-3333-333333333333"
    job.mkdir(parents=True)
    studio_module.write_json(job / "config.json", {"start": "2025-01-02", "end": "2025-06-30", "market": "csi300", "topk": 2, "n_drop": 1, "factors": [{"name": "STR_5"}]})
    studio_module.write_json(job / "result.json", {"status": "completed", "metrics": {"total_return": 0.01},
        "holdings": {"positions": [{"instrument": "SH600000", "amount": 100, "price": 10.0, "value": 1000.0, "weight": 0.5}], "cash": 1000.0, "total": 2000.0},
        "latest_signal": {"date": "2025-06-30", "universe": 300, "scores": [{"instrument": "SH600000", "score": 0.9, "rank": 1}, {"instrument": "SZ000001", "score": 0.8, "rank": 2}]}})
    body = {"name": "导出测试", "factors": [{"name": "STR_5", "weight": 1, "trace": "Finance Data Building/demo", "loop_id": 0}],
            "model": {"method": "rank"}, "params": {"market": "csi300", "benchmark": "SH000300", "topk": 2, "n_drop": 1, "account": 1000000, "open_cost": 0.0005, "close_cost": 0.0015},
            "evidence": {"backtest_id": "33333333-3333-3333-3333-333333333333", "start": "2025-01-02", "end": "2025-06-30"}}
    strategy = studio_client.post("/studio/strategies", json=body).get_json()
    payload = studio_client.get(f"/studio/strategies/{strategy['id']}/signal").get_json()
    assert payload["as_of"] == "2025-06-30" and payload["cash"] == 1000.0
    assert [(r["type"], r["instrument"]) for r in payload["rows"]] == [("holding", "SH600000"), ("score", "SH600000"), ("score", "SZ000001")]
    assert payload["rows"][1]["held"] is True and payload["rows"][2]["held"] is False
    csv_response = studio_client.get(f"/studio/strategies/{strategy['id']}/signal", query_string={"format": "csv"})
    assert csv_response.status_code == 200 and csv_response.mimetype == "text/csv"
    assert csv_response.headers["Content-Disposition"].encode("latin-1")  # non-ASCII names must be percent-encoded
    lines = csv_response.get_data(as_text=True).strip().splitlines()
    assert lines[0] == "date,type,instrument,name,weight,amount,price,value,score,rank,held" and len(lines) == 4
    # A strategy whose runs are not completed has nothing to export yet.
    studio_module.write_json(job / "result.json", {"status": "running"})
    assert studio_client.get(f"/studio/strategies/{strategy['id']}/signal").status_code == 409


def _report_rows(returns, bench):
    equity = benchmark = 1.0
    rows = []
    for i, (r, b) in enumerate(zip(returns, bench)):
        equity *= 1 + r
        benchmark *= 1 + b
        rows.append({"date": str(pd.Timestamp("2025-01-01") + pd.Timedelta(days=i)), "equity": equity, "benchmark": benchmark,
                     "drawdown": 0.0, "return": r, "cost": 0.0, "turnover": 0.0, "account": equity})
    for row in rows:
        row["date"] = row["date"][:10]
    return rows


@pytest.mark.offline
def test_style_spreads_take_top_minus_bottom_quintile_by_prior_value() -> None:
    from rdagent.log.server.studio_worker import STYLES, style_spreads

    names = [f"S{i}" for i in range(10)]
    index = pd.MultiIndex.from_product([pd.to_datetime(["2025-01-02", "2025-01-03"]), names], names=["datetime", "instrument"])
    frame = pd.DataFrame(index=index)
    frame["ret"] = [i / 100 for i in range(10)] * 2                  # return rises with the name's index
    for name in STYLES:
        frame[name] = [float(i) for i in range(10)] * 2               # every style ranks the names the same way
    frame.loc[(pd.Timestamp("2025-01-03"), slice(None)), "liquidity"] = float("nan")
    rows = style_spreads(frame)
    assert rows[0]["date"] == "2025-01-02" and rows[0]["momentum"] == pytest.approx((0.08 + 0.09) / 2 - (0.0 + 0.01) / 2)
    assert rows[1]["liquidity"] is None and rows[1]["reversal"] == rows[0]["reversal"]


@pytest.mark.offline
def test_fit_exposures_recovers_the_betas_and_bench_returns_undo_the_curve() -> None:
    import numpy as np
    from rdagent.log.server.studio_worker import STYLES, bench_returns, fit_exposures

    rng = np.random.default_rng(0)
    bench = rng.normal(0, 0.01, 60)
    styles = [{"date": f"2025-01-{i + 1:02d}", **{name: float(rng.normal(0, 0.005)) for name in STYLES}} for i in range(60)]
    for i in range(60):
        styles[i]["date"] = str((pd.Timestamp("2025-01-01") + pd.Timedelta(days=i)).date())
    returns = [0.0005 + 0.8 * bench[i] + 0.5 * styles[i]["momentum"] - 0.3 * styles[i]["reversal"] for i in range(60)]
    rows = _report_rows(returns, bench)
    assert bench_returns(rows) == pytest.approx(list(bench))
    fit = fit_exposures(rows, styles)
    assert fit["days"] == 60 and fit["r2"] == pytest.approx(1.0)
    assert fit["betas"]["alpha"] == pytest.approx(0.0005) and fit["betas"]["market"] == pytest.approx(0.8)
    assert fit["betas"]["momentum"] == pytest.approx(0.5) and fit["betas"]["reversal"] == pytest.approx(-0.3) and fit["betas"]["volatility"] == pytest.approx(0.0, abs=1e-9)
    assert fit_exposures(rows[:10], styles) is None


@pytest.mark.offline
def test_recent_context_places_the_last_week_in_the_runs_history() -> None:
    from rdagent.log.server.studio_worker import STYLES, recent_context

    # 60 quiet days, then a week that loses 1% a day while the benchmark loses 1.2% a day.
    returns = [0.001] * 55 + [-0.01] * 5
    bench = [0.0005] * 55 + [-0.012] * 5
    result = {"rows": _report_rows(returns, bench)}
    context = recent_context(result)
    week, month = context["horizons"]
    assert week["key"] == "week" and week["days"] == 5 and context["as_of"] == result["rows"][-1]["date"]
    assert week["return"] == pytest.approx((1 - 0.01) ** 5 - 1) and week["excess"] > 0
    assert week["percentile"] < 0.02 and week["windows"] == 56 and week["reading"] == "needs_update"
    assert month["percentile"] < 0.05 and "ic" not in week and "attribution" not in week
    # With daily IC and exposures stored, the week is explained: a normal IC and a market beta of 1 make it "market".
    result["ic_rows"] = [{"date": r["date"], "ic": 0.02, "rank_ic": 0.02} for r in result["rows"]]
    result["style_rows"] = [{"date": r["date"], **{name: 0.0 for name in STYLES}} for r in result["rows"]]
    result["attribution"] = {"betas": {"alpha": 0.0, "market": 1.0, **{name: 0.0 for name in STYLES}}, "r2": 0.9, "days": 60}
    week = recent_context(result)["horizons"][0]
    assert week["ic"]["recent"] == pytest.approx(0.02) and week["ic"]["percentile"] == pytest.approx(0.5)
    assert week["attribution"]["market"] == pytest.approx(-0.06) and week["attribution"]["residual"] == pytest.approx(0.01)
    assert week["reading"] == "market"
    assert week["ic"]["lag"] == 0 and week["ic"]["end"] == result["rows"][-1]["date"]
    # A collapsing IC over the same week reads as drift instead.
    for row in result["ic_rows"][-5:]:
        row["ic"] = -0.05
    assert recent_context(result)["horizons"][0]["reading"] == "drift"
    # A 20-day label leaves the last 20 days without IC: the newest complete window is used and dated.
    result["ic_rows"] = [{"date": r["date"], "ic": 0.02, "rank_ic": 0.02} for r in result["rows"][:-20]]
    week = recent_context(result)["horizons"][0]
    # ``end`` is the last day that has an IC at all, ``lag`` how far that trails the return window.
    assert week["ic"]["recent"] == pytest.approx(0.02) and week["ic"]["lag"] == 20 and week["ic"]["end"] == result["rows"][-21]["date"]
    assert week["reading"] == "market"  # judged on the newest IC there is, not "needs update"
    # A normal week is normal whatever else is stored.
    result["rows"] = _report_rows([0.001] * 60, [0.0005] * 60)
    assert recent_context(result)["horizons"][0]["reading"] == "normal"
    assert recent_context({"rows": result["rows"][:8]}) is None


def _signal_file(folder: Path, end: str) -> None:
    days = pd.bdate_range("2025-01-02", end)
    index = pd.MultiIndex.from_product([days, ["SH600000", "SZ000001"]], names=["datetime", "instrument"])
    folder.mkdir(parents=True, exist_ok=True)
    pd.DataFrame({"x": range(len(index))}, index=index, dtype=float).to_hdf(folder / "result.h5", key="data")


def _wait_for(predicate, timeout: float = 5.0) -> None:
    import time

    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return
        time.sleep(0.02)
    raise AssertionError("condition not met in time")


@pytest.mark.offline
def test_launch_recomputes_signals_that_stop_before_the_window(studio_client, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    ws = tmp_path / "ws" / "f0"
    _signal_file(ws, "2025-06-30")
    (ws / "factor.py").write_text("print(1)")
    refreshed, started = [], []

    def fake_refresh(code_path, name, out_dir, market="csi300"):
        refreshed.append((Path(code_path).name, name, market))
        _signal_file(Path(out_dir), "2025-12-31")
        (Path(out_dir) / "meta.json").write_text(json.dumps({"name": name, "start": "2025-01-02", "end": "2025-12-31"}))

    monkeypatch.setattr(studio_module, "run_refresh", fake_refresh)
    monkeypatch.setattr(studio_module.subprocess, "Popen", lambda cmd, **k: started.append(cmd) or type("P", (), {"poll": lambda self: None, "returncode": None})())
    body = {"factors": [{"name": "STR_5", "weight": 1, "trace": "Finance Data Building/demo", "loop_id": 0}], "start": "2025-03-03", "end": "2025-12-31",
            "market": "csi300", "benchmark": "SH000300", "topk": 10, "n_drop": 2, "account": 1000000, "open_cost": 0.0005, "close_cost": 0.0015}
    response = studio_client.post("/studio/backtests", json=body)
    assert response.status_code == 202, response.get_json()
    folder = studio_module.ROOT / response.get_json()["id"]
    _wait_for(lambda: bool(started))
    assert refreshed == [("factor.py", "STR_5", "csi300")]
    config = json.loads((folder / "config.json").read_text())
    assert config["factors"][0]["path"] == str(studio_module.refresh_dir("Finance Data Building/demo", 0, "STR_5"))
    assert json.loads((folder / "result.json").read_text())["message"].startswith("信号已重算")
    # A window the signal already covers starts the worker at once, without recomputing anything.
    refreshed.clear(); started.clear()
    response = studio_client.post("/studio/backtests", json={**body, "end": "2025-06-30"})
    assert response.status_code == 202 and started and refreshed == []
    # When recomputing fails the job fails with the cause and what to do instead of a coverage error later.
    monkeypatch.setattr(studio_module, "run_refresh", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("factor.py exited 1")))
    started.clear()
    # The refreshed copy from the first run would cover the window; point the test at a longer one.
    response = studio_client.post("/studio/backtests", json={**body, "end": "2026-06-30"})
    folder = studio_module.ROOT / response.get_json()["id"]
    _wait_for(lambda: json.loads((folder / "result.json").read_text()).get("status") == "failed")
    error = json.loads((folder / "result.json").read_text())["error"]
    assert "重算 STR_5 失败" in error and "factor.py exited 1" in error and "2025-12-31" in error and started == []


@pytest.mark.offline
def test_cross_universe_backtest_recomputes_the_factor_on_that_universe(studio_client, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A CSI300 factor requested on CSI1000 resolves to a per-universe copy, computed before the worker starts;
    the own-universe copy is never overwritten and the next request reuses the copy."""
    ws = tmp_path / "ws" / "f0"
    _signal_file(ws, "2025-12-31")
    (ws / "factor.py").write_text("print(1)")
    trace, own = "Finance Data Building/demo", studio_module.refresh_dir("Finance Data Building/demo", 0, "STR_5")
    other = studio_module.refresh_dir(trace, 0, "STR_5", "csi1000")
    assert other != own and studio_module.refresh_dir(trace, 0, "STR_5", "csi300") == own  # csi300 is the trace's own universe
    with server.app.app_context():
        resolved = studio_module.resolve_factor_paths(None, None, [{"name": "STR_5", "weight": 1, "trace": trace, "loop_id": 0}], market="csi1000")
        assert resolved[0]["recompute_for"] == "csi1000" and resolved[0]["path"] == str(ws)
        assert "recompute_for" not in studio_module.resolve_factor_paths(None, None, [{"name": "STR_5", "weight": 1, "trace": trace, "loop_id": 0}], market="csi300")[0]
    refreshed, started = [], []

    def fake_refresh(code_path, name, out_dir, market="csi300"):
        refreshed.append((name, market, Path(out_dir)))
        _signal_file(Path(out_dir), "2025-12-31")
        (Path(out_dir) / "meta.json").write_text(json.dumps({"name": name, "start": "2025-01-02", "end": "2025-12-31"}))

    monkeypatch.setattr(studio_module, "run_refresh", fake_refresh)
    monkeypatch.setattr(studio_module.subprocess, "Popen", lambda cmd, **k: started.append(cmd) or type("P", (), {"poll": lambda self: None, "returncode": None})())
    body = {"factors": [{"name": "STR_5", "weight": 1, "trace": trace, "loop_id": 0}], "start": "2025-03-03", "end": "2025-12-31",
            "market": "csi1000", "benchmark": "SH000852", "topk": 10, "n_drop": 2, "account": 1000000, "open_cost": 0.0005, "close_cost": 0.0015}
    response = studio_client.post("/studio/backtests", json=body)
    assert response.status_code == 202, response.get_json()
    folder = studio_module.ROOT / response.get_json()["id"]
    _wait_for(lambda: bool(started))
    assert refreshed == [("STR_5", "csi1000", other)] and not (own / "result.h5").exists()
    config = json.loads((folder / "config.json").read_text())
    assert config["factors"][0]["path"] == str(other) and "recompute_for" not in config["factors"][0]
    # Second request on csi1000: the copy exists, nothing is recomputed, the worker starts at once.
    refreshed.clear(); started.clear()
    assert studio_client.post("/studio/backtests", json=body).status_code == 202 and started and refreshed == []


@pytest.mark.offline
def test_signal_shortfall_names_the_short_signal() -> None:
    from rdagent.log.server.studio_worker import signal_shortfall

    days = pd.to_datetime(["2025-01-02", "2025-01-03"])
    index = pd.MultiIndex.from_product([days, ["A", "B"]], names=["datetime", "instrument"])
    ranks = pd.DataFrame({"long": [0.2, 0.8, 0.3, 0.7], "short": [0.5, 0.5, float("nan"), float("nan")]}, index=index)
    message = signal_shortfall(ranks, "2025-01-03")
    assert "short（到 2025-01-02）" in message and "long" not in message and "重算到最新" in message
    assert signal_shortfall(ranks, "2025-01-02") == ""


@pytest.mark.offline
def test_strategy_recent_reads_the_newest_completed_run(studio_client, tmp_path: Path) -> None:
    job = studio_module.ROOT / "55555555-5555-5555-5555-555555555555"
    job.mkdir(parents=True)
    studio_module.write_json(job / "config.json", {"start": "2025-01-01", "end": "2025-03-01", "factors": [{"name": "STR_5"}], "market": "csi300", "topk": 5, "n_drop": 1})
    studio_module.write_json(job / "result.json", {"status": "completed", "metrics": {"total_return": 0.05}, "rows": _report_rows([0.001] * 55 + [-0.01] * 5, [0.0005] * 60)})
    body = {"name": "近期", "factors": [{"name": "STR_5", "weight": 1, "trace": "Finance Data Building/demo", "loop_id": 0}], "model": {"method": "rank"},
            "params": {"market": "csi300", "benchmark": "SH000300", "topk": 5, "n_drop": 1, "account": 1000000, "open_cost": 0.0005, "close_cost": 0.0015},
            "evidence": {"backtest_id": "55555555-5555-5555-5555-555555555555", "start": "2025-01-01", "end": "2025-03-01"}}
    strategy = studio_client.post("/studio/strategies", json=body).get_json()
    recent = studio_client.get(f"/studio/strategies/{strategy['id']}/recent")
    assert recent.status_code == 200, recent.get_json()
    payload = recent.get_json()
    assert payload["backtest_id"] == "55555555-5555-5555-5555-555555555555" and payload["run_kind"] == "evidence"
    assert payload["has_ic"] is False and payload["window_end"] == "2025-03-01" and [h["key"] for h in payload["horizons"]] == ["week", "month"]
    assert payload["horizons"][0]["reading"] == "needs_update"
    studio_module.write_json(job / "result.json", {"status": "running"})
    assert studio_client.get(f"/studio/strategies/{strategy['id']}/recent").status_code == 409
    assert studio_client.get("/studio/strategies/00000000-0000-0000-0000-000000000000/recent").status_code == 404


@pytest.mark.offline
def test_research_from_strategy_seeds_base_features(studio_client, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (tmp_path / "ws" / "f0" / "factor.py").write_text("print('STR_5')")
    monkeypatch.setattr(server, "upload_folder_path", tmp_path / "uploads")
    monkeypatch.setattr(server, "universe_env", lambda market, build=True: {"QLIB_FACTOR_MARKET": market})
    started = []
    monkeypatch.setattr(server.RDAgentTask, "start", lambda self: started.append(self))
    body = {"name": "回流测试", "factors": [{"name": "STR_5", "weight": 1, "trace": "Finance Data Building/demo", "loop_id": 0}],
            "model": {"method": "rank"}, "params": {"market": "csi300", "benchmark": "SH000300", "topk": 10, "n_drop": 2, "account": 1000000, "open_cost": 0.0005, "close_cost": 0.0015}}
    strategy = studio_client.post("/studio/strategies", json=body).get_json()
    response = studio_client.post("/research/from-strategy", json={"strategy_id": strategy["id"], "loops": 2, "all_duration": 1})
    assert response.status_code == 200, response.get_json()
    payload = response.get_json()
    assert payload["members"] == ["STR_5"] and payload["id"].startswith("Finance Data Building/") and payload["id"].endswith("-on-strategy")
    assert "STR_5" in payload["instruction"] and "回流测试" in payload["instruction"]
    task = started[0]
    assert task.target_name == "fin_factor" and task.kwargs["loop_n"] == 2 and task.kwargs["all_duration"] == "1.0h"
    assert {k: v for k, v in task.env.items() if not k.endswith("_N_JOBS")} == {"QLIB_FACTOR_MARKET": "csi300"}
    base = Path(task.kwargs["base_features_path"])
    assert (base / "STR_5.py").read_text() == "print('STR_5')"
    assert studio_client.post("/research/from-strategy", json={"strategy_id": "nope"}).status_code == 404


@pytest.mark.offline
def test_universe_env_keeps_csi300_defaults_and_builds_others(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    provider = tmp_path / "qlib"
    (provider / "instruments").mkdir(parents=True)
    for name in ("csi300", "csi1000", "all"):
        (provider / "instruments" / f"{name}.txt").write_text("SH600000\t2020-01-01\t2030-01-01\n")
    monkeypatch.setenv("QLIB_PROVIDER_URI", str(provider))
    monkeypatch.setattr(server.UI_SETTING, "trace_folder", str(tmp_path / "traces"))
    assert server.available_universes() == ["csi300", "csi1000", "all"]
    env = server.universe_env("csi300")
    assert env["QLIB_FACTOR_MARKET"] == "csi300" and env["QLIB_MODEL_BENCHMARK"] == "SH000300" and "FACTOR_COSTEER_DATA_FOLDER" not in env
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        out = Path(cmd[6]); (out / "full").mkdir(parents=True, exist_ok=True); (out / "full" / "daily_pv.h5").write_bytes(b"")
        return type("P", (), {"stdout": '{"status": "completed"}', "stderr": ""})()

    monkeypatch.setattr(server.subprocess, "run", fake_run)
    env = server.universe_env("csi1000")
    assert env["QLIB_FACTOR_MARKET"] == "csi1000" and env["QLIB_FACTOR_BENCHMARK"] == "SH000852"
    assert env["QLIB_FACTOR_REGION"] == "cn" and env["QLIB_FACTOR_LIMIT_THRESHOLD"] == "0.095" and "QLIB_PROVIDER_URI" not in env
    assert env["FACTOR_COSTEER_DATA_FOLDER"].endswith("universe/csi1000/full") and calls and calls[0][3] == "csi1000" and calls[0][-1] == "cn"
    server.universe_env("csi1000")  # already built: no second subprocess
    assert len(calls) == 1
    with pytest.raises(ValueError):
        server.universe_env("nasdaq")
    # A sibling data directory declaring its universes (US data) joins the list with its own region and rules.
    us = tmp_path / "us_ndx"
    (us / "instruments").mkdir(parents=True)
    (us / "instruments" / "nasdaq100.txt").write_text("AAPL\t2020-01-01\t2030-01-01\n")
    (us / "instruments" / "us500.txt").write_text("AAPL\t2020-01-01\t2030-01-01\nJPM\t2020-01-01\t2030-01-01\n")
    (us / "studio-universe.json").write_text(json.dumps({"region": "us", "label": "美股", "benchmark": "^ndx", "benchmarks": {"us500": "^gspc"},
                                                        "markets": {"nasdaq100": "纳斯达克 100", "us500": "美股大盘 500", "sp500": "S&P 500"}}))
    assert server.available_universes() == ["csi300", "csi1000", "all", "nasdaq100", "us500"]  # sp500 has no instruments file
    env = server.universe_env("nasdaq100")
    assert env["QLIB_FACTOR_REGION"] == "us" and env["QLIB_FACTOR_BENCHMARK"] == "^ndx" and env["QLIB_FACTOR_LIMIT_THRESHOLD"] == "null"
    assert env["QLIB_FACTOR_OPEN_COST"] == "0.0001" and env["QLIB_FACTOR_CLOSE_COST"] == "0.0001"
    assert env["QLIB_PROVIDER_URI"] == env["QLIB_FACTOR_PROVIDER_URI"] == str(us)
    assert calls[-1][2] == str(us) and calls[-1][3] == "nasdaq100" and calls[-1][-1] == "us"
    from rdagent.log.server import studio_markets
    record = studio_markets.universe("nasdaq100")
    assert record["limit_threshold"] is None and record["min_cost"] == 1 and record["label"] == "纳斯达克 100"
    # A market with its own benchmark in the manifest uses it; the others keep the provider's.
    assert studio_markets.universe("us500")["benchmark"] == "^gspc" and record["benchmark"] == "^ndx"
    assert server.universe_env("us500")["QLIB_FACTOR_BENCHMARK"] == "^gspc"


@pytest.mark.offline
def test_universe_export_is_stale_only_when_the_window_can_grow(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """An export capped by QLIB_FACTOR_TEST_END is complete even when the Qlib calendar runs further; rebuilding it
    would produce the same file and, with build=False, an endless 'not ready' answer (the nasdaq100 loop)."""
    provider = tmp_path / "qlib"
    (provider / "instruments").mkdir(parents=True)
    (provider / "instruments" / "csi300.txt").write_text("SH600000\t2020-01-01\t2030-01-01\n")
    (provider / "calendars").mkdir()
    (provider / "calendars" / "day.txt").write_text("2025-01-02\n2026-09-15\n")
    (provider / "instruments" / "csi1000.txt").write_text("SH600000\t2020-01-01\t2030-01-01\n")
    monkeypatch.setenv("QLIB_PROVIDER_URI", str(provider))
    monkeypatch.setenv("QLIB_FACTOR_TEST_END", "2025-12-31")
    monkeypatch.setattr(server.UI_SETTING, "trace_folder", str(tmp_path / "traces"))
    out = tmp_path / "traces" / "studio_data" / "universe" / "csi1000"
    (out / "full").mkdir(parents=True); (out / "full" / "daily_pv.h5").write_bytes(b"")
    (out / "meta.json").write_text(json.dumps({"market": "csi1000", "start": "2022-10-03", "end": "2025-12-31"}))
    calls = []
    monkeypatch.setattr(server.subprocess, "run", lambda cmd, **kw: calls.append(cmd) or type("P", (), {"stdout": '{"status": "completed"}', "stderr": ""})())
    env = server.universe_env("csi1000", build=False)  # complete up to the configured end: ready, no job
    assert env["FACTOR_COSTEER_DATA_FOLDER"].endswith("csi1000/full") and not calls
    monkeypatch.setenv("QLIB_FACTOR_TEST_END", "2030-12-31")  # window open-ended: the export stops at 2025-12-31 while data reaches 2026-09-15
    with pytest.raises(server.UniverseNotReady):
        server.universe_env("csi1000", build=False)
    (out / "meta.json").write_text(json.dumps({"market": "csi1000", "start": "2022-10-03", "end": "2026-09-15"}))
    assert server.universe_env("csi1000", build=False)["FACTOR_COSTEER_DATA_FOLDER"].endswith("csi1000/full")


@pytest.mark.offline
def test_upload_passes_the_universe_to_the_run(studio_client, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(server, "upload_folder_path", tmp_path / "uploads")
    monkeypatch.setattr(server, "universe_env", lambda market, build=True: {"QLIB_FACTOR_MARKET": market, "FACTOR_COSTEER_DATA_FOLDER": "/data/" + market})
    started = []
    monkeypatch.setattr(server.RDAgentTask, "start", lambda self: started.append(self))
    response = studio_client.post("/upload", data={"scenario": "Finance Data Building", "loops": "2", "all_duration": "1", "market": "csi1000"})
    assert response.status_code == 200, response.get_json()
    assert {k: v for k, v in started[0].env.items() if not k.endswith("_N_JOBS")} == {"QLIB_FACTOR_MARKET": "csi1000", "FACTOR_COSTEER_DATA_FOLDER": "/data/csi1000"}
    assert started[0].kwargs["loop_n"] == 2


@pytest.mark.offline
def test_data_sync_status_settings_and_guards(studio_client, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from rdagent.log.server import studio_sync

    provider = tmp_path / "qlib"
    (provider / "calendars").mkdir(parents=True)
    (provider / "calendars" / "day.txt").write_text("2025-01-02\n2026-09-11\n")
    (provider / "studio-data-source.json").write_text(json.dumps({"release": "2026-09-12", "downloaded_at": "x"}))
    monkeypatch.setenv("QLIB_PROVIDER_URI", str(provider))
    monkeypatch.setattr(studio_sync, "_settings_path", tmp_path / "sync.json")
    status = studio_client.get("/studio/data/sync").get_json()
    assert status["local"]["release"] == "2026-09-12" and status["local"]["calendar_end"] == "2026-09-11"
    assert status["settings"]["auto"] is False and status["sync"]["running"] is False
    saved = studio_client.put("/studio/data/sync/settings", json={"auto": True, "hour": 20}).get_json()
    assert saved["auto"] is True and saved["hour"] == 20
    assert studio_client.put("/studio/data/sync/settings", json={"hour": 99}).status_code == 400
    # Already on the latest release: nothing to do; a running worker blocks the start.
    monkeypatch.setattr(studio_sync, "check_remote", lambda max_age=900: {"release": "2026-09-12", "archive_url": "u", "archive_bytes": 1})
    monkeypatch.setattr(studio_sync, "_busy_check", lambda: False)
    response = studio_client.post("/studio/data/sync", json={})
    assert response.status_code == 409 and "已是最新版" in response.get_json()["reason"]
    monkeypatch.setattr(studio_sync, "_busy_check", lambda: True)
    assert "正在运行" in studio_client.post("/studio/data/sync", json={"force": True}).get_json()["reason"]


@pytest.mark.offline
def test_sync_worker_swaps_directories_and_records_the_release(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import io
    import tarfile
    from rdagent.log.server import studio_sync

    provider = tmp_path / "qlib" / "cn_data"
    (provider / "calendars").mkdir(parents=True)
    (provider / "calendars" / "day.txt").write_text("2025-01-02\n")
    monkeypatch.setenv("QLIB_PROVIDER_URI", str(provider))
    monkeypatch.setattr(studio_sync, "_busy_check", lambda: False)
    # A fake archive with the layout of the real one: qlib_bin/calendars/day.txt ...
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as tar:
        for name, content in (("qlib_bin/calendars/day.txt", "2025-01-02\n2026-09-15\n"), ("qlib_bin/features/sh600000/close.day.bin", "x")):
            info = tarfile.TarInfo(name); data = content.encode(); info.size = len(data); tar.addfile(info, io.BytesIO(data))
    archive_bytes = buffer.getvalue()
    monkeypatch.setattr(studio_sync, "_download", lambda url, target, expected: target.write_bytes(archive_bytes))
    monkeypatch.setattr(studio_sync, "_get_json", lambda url, timeout=20: {"archive_sha256": "sha256:" + __import__("hashlib").sha256(archive_bytes).hexdigest()})
    studio_sync._sync_worker({"release": "2026-09-15", "archive_url": "u", "archive_bytes": len(archive_bytes), "manifest_url": "m", "published_at": "p"})
    assert (provider / "calendars" / "day.txt").read_text().splitlines()[-1] == "2026-09-15"
    assert (provider / "features" / "sh600000" / "close.day.bin").is_file()
    source = json.loads((provider / "studio-data-source.json").read_text())
    assert source["release"] == "2026-09-15" and source["calendar_end"] == "2026-09-15"
    assert not (provider.parent / "cn_data.old").exists() and not (provider.parent / "cn_data.new").exists()
    assert studio_sync.status()["sync"]["phase"] == "done"


@pytest.mark.offline
def test_rounds_lists_factor_rounds(studio_client) -> None:
    response = studio_client.get("/studio/rounds", query_string={"trace": "Finance Data Building/demo"})
    assert response.status_code == 200
    assert response.get_json() == [{"loop_id": 0, "factors": ["STR_5"], "metrics": {"IC": 0.01, "Rank IC": 0.02}, "prediction": False}]
    assert studio_client.get("/studio/rounds", query_string={"trace": "nope/none"}).status_code == 404


@pytest.mark.offline
def test_backtest_resolves_factor_paths(studio_client, tmp_path: Path) -> None:
    body = {"trace": "Finance Data Building/demo", "loop_id": 0,
            "factors": [{"name": "STR_5", "weight": 1}],
            "start": "2025-01-01", "end": "2025-06-30", "market": "csi300",
            "topk": 10, "n_drop": 2, "account": 1000000, "open_cost": 0.0005, "close_cost": 0.0015,
            "provider_uri": str(tmp_path / "qlib")}
    (tmp_path / "qlib" / "calendars").mkdir(parents=True)
    (tmp_path / "qlib" / "calendars" / "day.txt").write_text("2025-01-02\n")
    response = studio_client.post("/studio/backtests", json=body)
    assert response.status_code == 202, response.get_json()
    job = response.get_json()["id"]
    config = json.loads((tmp_path / "traces" / "studio_backtests" / job / "config.json").read_text())
    assert config["factors"] == [{"name": "STR_5", "kind": "factor", "weight": 1.0, "path": str(tmp_path / "ws" / "f0"),
                                  "trace": "Finance Data Building/demo", "loop_id": 0}]
    assert config["trace"] == "Finance Data Building/demo"
    assert config["region"] == "cn" and config["limit_threshold"] == 0.095 and config["min_cost"] == 5 and config["benchmark"] == "SH000300"

    bad = dict(body, factors=[{"name": "UNKNOWN", "weight": 1}])
    assert studio_client.post("/studio/backtests", json=bad).status_code == 400


@pytest.mark.offline
def test_backtest_rejects_paths_outside_workspace_root(studio_client, tmp_path: Path) -> None:
    task = server.rdagent_processes[str(tmp_path / "traces" / "Finance Data Building/demo")]
    task.messages[1]["content"]["workspaces"]["factors"][0]["path"] = str(tmp_path / "elsewhere")
    body = {"trace": "Finance Data Building/demo", "loop_id": 0,
            "factors": [{"name": "STR_5", "weight": 1}],
            "start": "2025-01-01", "end": "2025-06-30", "market": "csi300",
            "topk": 10, "n_drop": 2, "account": 1000000, "open_cost": 0.0005, "close_cost": 0.0015}
    response = studio_client.post("/studio/backtests", json=body)
    assert response.status_code == 400
    assert "workspace" in response.get_json()["error"].lower()


@pytest.mark.offline
def test_research_reports_route_removed(studio_client) -> None:
    assert studio_client.get("/studio/research-reports").status_code == 404


@pytest.mark.offline
def test_backtest_accepts_string_loop_id(studio_client, tmp_path: Path) -> None:
    body = {"trace": "Finance Data Building/demo", "loop_id": "0",
            "factors": [{"name": "STR_5", "weight": 1}],
            "start": "2025-01-01", "end": "2025-06-30", "market": "csi300",
            "topk": 10, "n_drop": 2, "account": 1000000, "open_cost": 0.0005, "close_cost": 0.0015,
            "provider_uri": str(tmp_path / "qlib")}
    (tmp_path / "qlib" / "calendars").mkdir(parents=True)
    (tmp_path / "qlib" / "calendars" / "day.txt").write_text("2025-01-02\n")
    response = studio_client.post("/studio/backtests", json=body)
    assert response.status_code == 202, response.get_json()
    job = response.get_json()["id"]
    config = json.loads((tmp_path / "traces" / "studio_backtests" / job / "config.json").read_text())
    assert config["loop_id"] == 0


@pytest.mark.offline
def test_backtest_rejects_non_numeric_loop_id(studio_client, tmp_path: Path) -> None:
    body = {"trace": "Finance Data Building/demo", "loop_id": "x",
            "factors": [{"name": "STR_5", "weight": 1}],
            "start": "2025-01-01", "end": "2025-06-30", "market": "csi300",
            "topk": 10, "n_drop": 2, "account": 1000000, "open_cost": 0.0005, "close_cost": 0.0015}
    response = studio_client.post("/studio/backtests", json=body)
    assert response.status_code == 400
    assert "loop_id" in response.get_json()["error"]


@pytest.mark.offline
def test_trace_messages_reads_registry_from_current_app(tmp_path: Path) -> None:
    """trace_messages must go through current_app.config, not `import rdagent.log.server.app`.

    A plain dotted import of that module is wrong at runtime: the real server process is
    started with `python -m rdagent.log.server.app`, which binds the running module to
    sys.modules["__main__"] and leaves a second, never-populated copy under its normal
    dotted name. Push a task into app.config["RDAGENT_PROCESSES"] directly (bypassing
    `server.rdagent_processes` as a plain module attribute) and confirm trace_messages
    still finds it purely via the Flask application context.
    """
    trace_folder = tmp_path / "traces"
    fake_task = type("FakeTask", (), {"messages": [{"tag": "feedback.metric"}]})()
    registry = {}
    with server.app.app_context():
        original_registry = server.app.config["RDAGENT_PROCESSES"]
        original_folder = server.app.config["LOG_FOLDER_PATH"]
        server.app.config["RDAGENT_PROCESSES"] = registry
        server.app.config["LOG_FOLDER_PATH"] = trace_folder
        try:
            registry[str(trace_folder / "some/trace")] = fake_task
            assert studio_module.trace_messages("some/trace") == fake_task.messages
            assert studio_module.trace_messages("missing/trace") is None
        finally:
            server.app.config["RDAGENT_PROCESSES"] = original_registry
            server.app.config["LOG_FOLDER_PATH"] = original_folder


@pytest.mark.offline
def test_require_signal_coverage_rejects_window_past_signal_history() -> None:
    dates = pd.DatetimeIndex(["2025-12-29", "2025-12-30", "2025-12-31"])
    with pytest.raises(ValueError) as excinfo:
        require_signal_coverage(dates, "2025-12-29", "2026-09-11")
    message = str(excinfo.value)
    assert "2025-12-29" in message
    assert "2025-12-31" in message


@pytest.mark.offline
def test_require_signal_coverage_accepts_window_inside_signal_history() -> None:
    dates = pd.DatetimeIndex(["2025-01-01", "2025-06-15", "2025-12-31"])
    require_signal_coverage(dates, "2025-01-02", "2025-12-30")


@pytest.mark.offline
def test_trading_day_on_or_before_rolls_back_from_weekend() -> None:
    calendar = pd.DatetimeIndex(["2025-01-01", "2025-01-02", "2025-01-03"])
    # 2025-01-04 is a Saturday, one day after the last trading day above.
    assert trading_day_on_or_before(calendar, "2025-01-04") == pd.Timestamp("2025-01-03")


@pytest.mark.offline
def test_trading_day_on_or_before_returns_exact_match() -> None:
    calendar = pd.DatetimeIndex(["2025-01-01", "2025-01-02", "2025-01-03"])
    assert trading_day_on_or_before(calendar, "2025-01-02") == pd.Timestamp("2025-01-02")


@pytest.mark.offline
def test_trading_day_on_or_before_rejects_date_before_calendar() -> None:
    calendar = pd.DatetimeIndex(["2025-01-01", "2025-01-02", "2025-01-03"])
    with pytest.raises(ValueError):
        trading_day_on_or_before(calendar, "2024-12-31")


@pytest.mark.offline
def test_running_workspaces_only_include_factor_tasks(tmp_path: Path) -> None:
    factor_task = _FactorTask("STR_5")
    model_task = _ModelTask(name="LGBModel", description="")
    exp = Experiment(sub_tasks=[factor_task, model_task])
    exp.experiment_workspace = FBWorkspace()
    exp.experiment_workspace.workspace_path = tmp_path / "exp"
    for index, task in enumerate([factor_task, model_task]):
        ws = FBWorkspace(target_task=task)
        ws.workspace_path = tmp_path / f"ws{index}"
        exp.sub_workspace_list[index] = ws
    exp.result = pd.Series({"IC": 0.01})
    data = WebStorage(port=1, path=tmp_path)._obj_to_json(
        obj=exp, tag="Loop_0.running", id="trace", timestamp="2026-09-14T00:00:00"
    )
    factors = data["msg"]["content"]["workspaces"]["factors"]
    assert [f["name"] for f in factors] == ["STR_5"]


@pytest.mark.offline
def test_metric_rounds_dedupes_keeping_latest_per_loop() -> None:
    messages = [
        {
            "tag": "feedback.metric", "loop_id": 0, "timestamp": "t1",
            "content": {"result": json.dumps({"IC": 0.01}),
                        "workspaces": {"factors": [{"name": "OLD", "path": "/tmp/old"}]}},
        },
        {
            "tag": "feedback.metric", "loop_id": 0, "timestamp": "t2",
            "content": {"result": json.dumps({"IC": 0.02}),
                        "workspaces": {"factors": [{"name": "NEW", "path": "/tmp/new"}]}},
        },
    ]
    rounds = studio_module.metric_rounds(messages)
    assert len(rounds) == 1
    assert rounds[0]["factors"] == ["NEW"]
    assert rounds[0]["metrics"] == {"IC": 0.02}


@pytest.mark.offline
def test_metric_rounds_excludes_bool_metrics() -> None:
    messages = [
        {
            "tag": "feedback.metric", "loop_id": 0, "timestamp": "t1",
            "content": {"result": json.dumps({"IC": 0.01, "ok": True}), "workspaces": {"factors": []}},
        },
    ]
    rounds = studio_module.metric_rounds(messages)
    assert rounds[0]["metrics"] == {"IC": 0.01}


@pytest.mark.offline
def test_resolve_factor_paths_rejects_non_dict_factor(studio_client) -> None:
    body = {"trace": "Finance Data Building/demo", "loop_id": 0,
            "factors": ["STR_5"],
            "start": "2025-01-01", "end": "2025-06-30", "market": "csi300",
            "topk": 10, "n_drop": 2, "account": 1000000, "open_cost": 0.0005, "close_cost": 0.0015}
    response = studio_client.post("/studio/backtests", json=body)
    assert response.status_code == 400
    assert "object with name and weight" in response.get_json()["error"]


@pytest.mark.offline
def test_backtest_responses_omit_factor_paths(studio_client, tmp_path: Path) -> None:
    body = {"trace": "Finance Data Building/demo", "loop_id": 0,
            "factors": [{"name": "STR_5", "weight": 1}],
            "start": "2025-01-01", "end": "2025-06-30", "market": "csi300",
            "topk": 10, "n_drop": 2, "account": 1000000, "open_cost": 0.0005, "close_cost": 0.0015,
            "provider_uri": str(tmp_path / "qlib")}
    (tmp_path / "qlib" / "calendars").mkdir(parents=True)
    (tmp_path / "qlib" / "calendars" / "day.txt").write_text("2025-01-02\n")
    post_response = studio_client.post("/studio/backtests", json=body)
    assert post_response.status_code == 202, post_response.get_json()
    job = post_response.get_json()["id"]

    for factor in studio_client.get("/studio/backtests").get_json()[0]["config"]["factors"]:
        assert "path" not in factor
    for factor in studio_client.get(f"/studio/backtests/{job}").get_json()["config"]["factors"]:
        assert "path" not in factor


@pytest.mark.offline
def test_backtest_accepts_per_factor_rounds_without_request_defaults(studio_client, tmp_path: Path) -> None:
    body = {"factors": [{"name": "STR_5", "weight": 1, "trace": "Finance Data Building/demo", "loop_id": "0"}],
            "start": "2025-01-01", "end": "2025-06-30", "market": "csi300", "benchmark": "SH000905",
            "topk": 10, "n_drop": 2, "account": 1000000, "open_cost": 0.0005, "close_cost": 0.0015,
            "provider_uri": str(tmp_path / "qlib")}
    (tmp_path / "qlib" / "calendars").mkdir(parents=True, exist_ok=True)
    (tmp_path / "qlib" / "calendars" / "day.txt").write_text("2025-01-02\n")
    response = studio_client.post("/studio/backtests", json=body)
    assert response.status_code == 202, response.get_json()
    config = json.loads((tmp_path / "traces" / "studio_backtests" / response.get_json()["id"] / "config.json").read_text())
    assert config["factors"][0]["loop_id"] == 0
    assert config["benchmark"] == "SH000905"
    listed = studio_client.get("/studio/backtests").get_json()[0]["config"]["factors"][0]
    assert listed == {"name": "STR_5", "kind": "factor", "weight": 1.0, "trace": "Finance Data Building/demo", "loop_id": 0}

    unknown = dict(body, factors=[{"name": "STR_5", "weight": 1, "trace": "nope/none", "loop_id": 0}])
    assert studio_client.post("/studio/backtests", json=unknown).status_code == 400


@pytest.mark.offline
def test_factor_library_lists_factors_with_code(studio_client, tmp_path: Path) -> None:
    task = server.rdagent_processes[str(tmp_path / "traces" / "Finance Data Building/demo")]
    task.messages.insert(1, {"tag": "evolving.codes", "loop_id": "0", "timestamp": "t", "evo_id": 0,
                             "content": [{"evo_id": 0, "target_task_name": "STR_5", "workspace": {"factor.py": "print(5)"}}]})
    task.messages.insert(1, {"tag": "research.tasks", "loop_id": "0", "timestamp": "t",
                             "content": [{"name": "STR_5", "description": "Short-term reversal", "formulation": "-r_5",
                                          "variables": {"$close": "close"}}]})
    task.messages.append({"tag": "feedback.hypothesis_feedback", "loop_id": "0", "timestamp": "t",
                          "content": {"decision": True, "reason": "improves return"}})
    response = studio_client.get("/studio/factors")
    assert response.status_code == 200
    assert response.get_json() == [{
        "trace": "Finance Data Building/demo", "loop_id": 0, "name": "STR_5", "market": "csi300",
        "description": "Short-term reversal", "formulation": "-r_5", "variables": {"$close": "close"},
        "hypothesis": "h", "decision": True, "reason": "improves return",
        "metrics": {"IC": 0.01, "Rank IC": 0.02}, "code": "print(5)", "analysis": None, "analysis_error": None, "refreshed": None, "coverage": None,
    }]


@pytest.mark.offline
def test_validate_config_checks_benchmark() -> None:
    with pytest.raises(ValueError, match="同名因子 STR_5"):
        validate_config(_config(factors=[{"name": "STR_5", "path": "/tmp/a", "weight": 1}, {"name": "STR_5", "path": "/tmp/b", "weight": 1}]))
    assert validate_config(_config())["benchmark"] == "SH000300"
    assert validate_config(_config(benchmark=" SH000905 "))["benchmark"] == "SH000905"
    with pytest.raises(ValueError, match="benchmark"):
        validate_config(_config(benchmark=""))


@pytest.mark.offline
def test_factor_library_falls_back_to_workspace_source(studio_client, tmp_path: Path) -> None:
    (tmp_path / "ws" / "f0" / "factor.py").write_text("print('from disk')")
    entry = studio_client.get("/studio/factors").get_json()[0]
    assert entry["code"] == "print('from disk')"


def _write_prediction(workspace_root: Path) -> Path:
    artifacts = workspace_root / "exp" / "mlruns" / "1" / "run" / "artifacts"
    artifacts.mkdir(parents=True, exist_ok=True)
    index = pd.MultiIndex.from_tuples(
        [(pd.Timestamp("2025-01-02"), "SH600000"), (pd.Timestamp("2025-01-02"), "SH600009")],
        names=["datetime", "instrument"],
    )
    path = artifacts / "pred.pkl"
    pd.DataFrame({"score": [0.2, 0.1]}, index=index).to_pickle(path)
    return path


@pytest.mark.offline
def test_rounds_report_prediction_availability(studio_client, tmp_path: Path) -> None:
    assert studio_client.get("/studio/rounds", query_string={"trace": "Finance Data Building/demo"}).get_json()[0]["prediction"] is False
    _write_prediction(tmp_path / "ws")
    rounds = studio_client.get("/studio/rounds", query_string={"trace": "Finance Data Building/demo"}).get_json()
    assert rounds[0]["prediction"] is True
    assert "experiment" not in rounds[0] and "paths" not in rounds[0]


@pytest.mark.offline
def test_backtest_accepts_model_prediction_signal(studio_client, tmp_path: Path) -> None:
    pred = _write_prediction(tmp_path / "ws")
    (tmp_path / "qlib" / "calendars").mkdir(parents=True, exist_ok=True)
    (tmp_path / "qlib" / "calendars" / "day.txt").write_text("2025-01-02\n")
    body = {"factors": [{"kind": "prediction", "name": "模型预测", "weight": 1,
                         "trace": "Finance Data Building/demo", "loop_id": 0}],
            "start": "2025-01-01", "end": "2025-06-30", "market": "csi300",
            "topk": 10, "n_drop": 2, "account": 1000000, "open_cost": 0.0005, "close_cost": 0.0015,
            "provider_uri": str(tmp_path / "qlib")}
    response = studio_client.post("/studio/backtests", json=body)
    assert response.status_code == 202, response.get_json()
    config = json.loads((tmp_path / "traces" / "studio_backtests" / response.get_json()["id"] / "config.json").read_text())
    assert config["factors"][0]["kind"] == "prediction"
    assert config["factors"][0]["path"] == str(pred)
    listed = studio_client.get("/studio/backtests").get_json()[0]["config"]["factors"][0]
    assert listed["kind"] == "prediction" and "path" not in listed


@pytest.mark.offline
def test_backtest_rejects_prediction_when_round_has_none(studio_client, tmp_path: Path) -> None:
    body = {"factors": [{"kind": "prediction", "name": "模型预测", "weight": 1,
                         "trace": "Finance Data Building/demo", "loop_id": 0}],
            "start": "2025-01-01", "end": "2025-06-30", "market": "csi300",
            "topk": 10, "n_drop": 2, "account": 1000000, "open_cost": 0.0005, "close_cost": 0.0015}
    response = studio_client.post("/studio/backtests", json=body)
    assert response.status_code == 400
    assert "prediction" in response.get_json()["error"]


@pytest.mark.offline
def test_load_factor_frame_reads_prediction_pickle(tmp_path: Path) -> None:
    pred = _write_prediction(tmp_path)
    frame = load_factor_frame({"kind": "prediction", "name": "模型预测", "path": str(pred)},
                              pd.Timestamp("2025-01-01"), "2025-12-31")
    assert list(frame.columns) == ["模型预测"]
    assert len(frame) == 2


class _Metric:
    def __init__(self, values):
        self._values = values

    def to_dict(self):
        return dict(self._values)


class _Indicator:
    """Mimics qlib's NumpyOrderIndicator: get_index_data(metric).to_dict() -> {instrument: value}."""

    def __init__(self, rows):
        self._rows = rows

    def get_index_data(self, metric):
        return _Metric({r["instrument"]: r[metric] for r in self._rows})


class _Position:
    def __init__(self, book, cash):
        self._book = book
        self._cash = cash

    def get_stock_list(self):
        return list(self._book)

    def get_stock_amount(self, code):
        return self._book[code][0]

    def get_stock_price(self, code):
        return self._book[code][1]

    def get_stock_weight(self, code):
        return self._book[code][0] * self._book[code][1] / self.calculate_value()

    def get_cash(self, include_settle=False):
        return self._cash

    def calculate_value(self):
        return self._cash + sum(a * p for a, p in self._book.values())


@pytest.mark.offline
def test_trades_and_holdings_are_flattened_for_the_ui() -> None:
    from rdagent.log.server.studio_worker import holdings_from_position, instrument_summary, trades_from_indicator

    his = {
        pd.Timestamp("2025-01-03"): _Indicator([
            {"instrument": "SH600000", "deal_amount": 100, "trade_price": 10.0, "trade_value": 1000.0, "trade_cost": 1.0, "trade_dir": 1},
            {"instrument": "SH600009", "deal_amount": 0, "trade_price": 0.0, "trade_value": 0.0, "trade_cost": 0.0, "trade_dir": 1},
        ]),
        pd.Timestamp("2025-01-06"): _Indicator([
            {"instrument": "SH600000", "deal_amount": 50, "trade_price": 12.0, "trade_value": -600.0, "trade_cost": 1.5, "trade_dir": 0},
        ]),
    }
    trades = trades_from_indicator(his)
    assert trades == [
        {"date": "2025-01-03", "instrument": "SH600000", "direction": "buy", "amount": 100.0, "price": 10.0, "value": 1000.0, "cost": 1.0},
        {"date": "2025-01-06", "instrument": "SH600000", "direction": "sell", "amount": 50.0, "price": 12.0, "value": 600.0, "cost": 1.5},
    ]
    holdings = holdings_from_position(_Position({"SH600000": (50, 13.0)}, cash=397.5))
    assert holdings["positions"] == [{"instrument": "SH600000", "amount": 50.0, "price": 13.0, "value": 650.0, "weight": 650.0 / 1047.5}]
    assert holdings["cash"] == 397.5
    summary = instrument_summary(trades, holdings)
    assert summary == [{"instrument": "SH600000", "trades": 2, "buy_value": 1000.0, "sell_value": 600.0, "cost": 2.5,
                        "holding_value": 650.0, "pnl": 247.5, "held": True}]
    # Qlib's adjusted price and share count become the broker's real ones through $factor; values stay put.
    from rdagent.log.server.studio_worker import unadjust_book

    holdings["as_of"] = "2025-01-06"
    trades, holdings = unadjust_book(trades, holdings, {("SH600000", "2025-01-03"): 0.5, ("SH600000", "2025-01-06"): 0.5})
    assert trades[0]["price"] == 20.0 and trades[0]["amount"] == 50.0 and trades[0]["value"] == 1000.0
    assert holdings["positions"][0] == {"instrument": "SH600000", "amount": 25.0, "price": 26.0, "value": 650.0, "weight": 650.0 / 1047.5}
    assert instrument_summary(trades, holdings)[0]["pnl"] == 247.5
    # A missing factor (instrument outside the data) leaves the row as Qlib produced it.
    trades, _ = unadjust_book([{"date": "2025-01-03", "instrument": "SH600009", "amount": 1.0, "price": 2.0, "value": 2.0, "cost": 0.0}], {"positions": []}, {})
    assert trades[0]["price"] == 2.0 and trades[0]["amount"] == 1.0


@pytest.mark.offline
def test_validate_model_defaults_to_rank_and_orders_lgbm_windows() -> None:
    from rdagent.log.server.studio_worker import LGBM_DEFAULTS, validate_model

    assert validate_model(None, "2025-01-02") == {"method": "rank"}
    model = validate_model({"method": "lgbm", "train": ["2023-01-01", "2023-12-31"], "valid": ["2024-01-01", "2024-12-31"],
                            "params": {"num_leaves": "31", "learning_rate": 0.1}}, "2025-01-02")
    assert model["train"] == ["2023-01-01", "2023-12-31"] and model["valid"] == ["2024-01-01", "2024-12-31"]
    assert model["params"]["num_leaves"] == 31 and model["params"]["learning_rate"] == 0.1
    assert model["params"]["n_estimators"] == LGBM_DEFAULTS["n_estimators"]
    for bad in (
        {"method": "lgbm", "train": ["2023-01-01", "2024-06-30"], "valid": ["2024-01-01", "2024-12-31"]},  # overlap
        {"method": "lgbm", "train": ["2023-01-01", "2023-12-31"], "valid": ["2024-01-01", "2025-03-31"]},  # leaks into backtest
        {"method": "lgbm", "train": ["2023-01-01", "2023-12-31"], "valid": ["2024-01-01", "2024-12-31"], "params": {"num_leaves": 1}},
        {"method": "lgbm", "train": ["2023-01-01", "2023-12-31"], "valid": ["2024-01-01", "2024-12-31"], "params": {"boosting": "dart"}},
        {"method": "mlp"},
    ):
        with pytest.raises(ValueError):
            validate_model(bad, "2025-01-02")


@pytest.mark.offline
def test_lgbm_signal_and_ic_on_synthetic_data() -> None:
    import numpy as np
    from rdagent.log.server.studio_worker import cross_sectional_zscore, information_coefficient, train_lgbm_signal

    rng = np.random.default_rng(0)
    days = pd.bdate_range("2024-01-01", periods=120)
    stocks = [f"S{i:03d}" for i in range(40)]
    index = pd.MultiIndex.from_product([days, stocks], names=["datetime", "instrument"])
    f1 = pd.Series(rng.normal(size=len(index)), index=index)
    f2 = pd.Series(rng.normal(size=len(index)), index=index)
    label_raw = 0.8 * f1 - 0.3 * f2 + 0.2 * rng.normal(size=len(index))
    features = pd.concat([f1.rename("f1"), f2.rename("f2")], axis=1).groupby(level="datetime").rank(pct=True)
    label = cross_sectional_zscore(pd.Series(label_raw, index=index))
    assert abs(label.groupby(level="datetime").mean()).max() < 1e-9

    model = {"method": "lgbm", "train": [str(days[0].date()), str(days[79].date())],
             "valid": [str(days[80].date()), str(days[99].date())],
             "params": {"learning_rate": 0.1, "num_leaves": 15, "max_depth": 4, "colsample_bytree": 1.0, "subsample": 1.0,
                        "subsample_freq": 0, "lambda_l1": 0.0, "lambda_l2": 1.0, "n_estimators": 200, "early_stopping_rounds": 20}}
    score, report = train_lgbm_signal(features, label, model, log=lambda *_: None)
    assert report["train_rows"] == 80 * 40 and report["valid_rows"] == 20 * 40
    assert set(report["feature_importance"]) == {"f1", "f2"}
    test = score[score.index.get_level_values("datetime") >= days[100]]
    ic, rank_ic = information_coefficient(test, label)
    assert ic is not None and ic > 0.5 and rank_ic > 0.5


@pytest.mark.offline
def test_window_coverage_names_the_missing_signal() -> None:
    from rdagent.log.server.studio_worker import require_window_coverage

    days = pd.bdate_range("2024-01-01", periods=10)
    index = pd.MultiIndex.from_product([days, ["A"]], names=["datetime", "instrument"])
    features = pd.DataFrame({"f1": 1.0, "pred": [None] * 5 + [1.0] * 5}, index=index)
    require_window_coverage(features, [str(days[5].date()), str(days[9].date())], "training")
    with pytest.raises(ValueError, match="pred \\(2024-01-08 to 2024-01-12\\)"):
        require_window_coverage(features, [str(days[0].date()), str(days[4].date())], "training")


@pytest.mark.offline
def test_factor_library_borrows_task_description_from_another_trace(studio_client, tmp_path: Path) -> None:
    other = server._get_or_create_task(str(tmp_path / "traces" / "Finance Data Building/original"))
    other.messages = [{"tag": "research.hypothesis", "loop_id": "0", "timestamp": "t", "content": {"hypothesis": "original idea"}},
                      {"tag": "research.tasks", "loop_id": "0", "timestamp": "t",
                       "content": [{"name": "STR_5", "description": "from the original run", "formulation": None, "variables": None}]}]
    task = server.rdagent_processes[str(tmp_path / "traces" / "Finance Data Building/demo")]
    task.messages = [m for m in task.messages if m["tag"] != "research.hypothesis"]
    entry = next(e for e in studio_client.get("/studio/factors").get_json() if e["trace"] == "Finance Data Building/demo")
    assert entry["description"] == "from the original run"
    assert entry["hypothesis"] == "original idea"


@pytest.mark.offline
def test_factor_correlation_ranks_and_averages(studio_client, tmp_path: Path) -> None:
    from rdagent.log.server.studio import factor_correlation

    days = pd.bdate_range("2025-01-01", periods=5)
    stocks = ["A", "B", "C", "D"]
    index = pd.MultiIndex.from_product([days, stocks], names=["datetime", "instrument"])
    base = pd.Series(range(len(index)), index=index, dtype=float)
    (tmp_path / "ws" / "f1").mkdir(parents=True)
    (tmp_path / "ws" / "f2").mkdir(parents=True)
    base.to_frame("x").to_hdf(tmp_path / "ws" / "f1" / "result.h5", key="data")
    (-base).to_frame("y").to_hdf(tmp_path / "ws" / "f2" / "result.h5", key="data")
    result = factor_correlation([("f1", tmp_path / "ws" / "f1"), ("f2", tmp_path / "ws" / "f2")])
    assert result["names"] == ["f1", "f2"] and result["days"] == 5
    assert result["matrix"][0][0] == pytest.approx(1.0) and result["matrix"][0][1] == pytest.approx(-1.0)


@pytest.mark.offline
def test_cached_analysis_is_invalidated_when_result_changes(tmp_path: Path) -> None:
    from rdagent.log.server.studio import analysis_cache_path, cached_analysis

    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "result.h5").write_bytes(b"x")
    fresh = {"status": "completed", "version": studio_module.ANALYSIS_VERSION, "source_mtime": (ws / "result.h5").stat().st_mtime, "days": 3}
    analysis_cache_path(ws, "csi300").write_text(json.dumps(fresh))
    assert cached_analysis(ws, "csi300")["days"] == 3
    analysis_cache_path(ws, "csi300").write_text(json.dumps({**fresh, "source_mtime": 0}))
    assert cached_analysis(ws, "csi300") is None
    # An analysis written by an older studio_analysis.py (no horizons, no t) is recomputed rather than shown.
    analysis_cache_path(ws, "csi300").write_text(json.dumps({**fresh, "version": 1}))
    assert cached_analysis(ws, "csi300") is None


@pytest.mark.offline
def test_analysis_summary_on_synthetic_ic() -> None:
    from rdagent.log.server.studio_analysis import daily_ic, summarize

    days = pd.bdate_range("2025-01-01", periods=30)
    stocks = [f"S{i}" for i in range(20)]
    index = pd.MultiIndex.from_product([days, stocks], names=["datetime", "instrument"])
    factor = pd.Series([i % 20 for i in range(len(index))], index=index, dtype=float)
    ic, rank_ic = daily_ic(factor, factor * 2)
    summary = summarize(ic, rank_ic, days[0], days[-1], len(index))
    assert summary["days"] == 30 and summary["ic"]["mean"] == pytest.approx(1.0) and summary["rank_ic"]["positive_ratio"] == 1.0
    assert summary["monthly"][0]["month"] == "2025-01" and summary["coverage"] == {"start": "2025-01-01", "end": "2025-02-11"}
    assert summary["horizons"] == [] and summary["verdict"] is None


@pytest.mark.offline
def test_factor_series_names_an_all_nan_signal(tmp_path: Path) -> None:
    from rdagent.log.server.studio_analysis import factor_series

    days = pd.bdate_range("2025-01-01", periods=5)
    index = pd.MultiIndex.from_product([days, ["A", "B"]], names=["datetime", "instrument"])
    pd.Series([float("nan")] * len(index), index=index).to_frame("x").to_hdf(tmp_path / "result.h5", key="data")
    with pytest.raises(ValueError, match="no valid values: all 10 rows are NaN over 2025-01-01 → 2025-01-07"):
        factor_series(tmp_path)


@pytest.mark.offline
def test_analysis_t_statistics_horizons_and_residual() -> None:
    import numpy as np
    from rdagent.log.server.studio_analysis import T_SIGNAL, label_expression, residualize, stats, verdict

    assert label_expression(1) == "Ref($close, -2)/Ref($close, -1) - 1" and label_expression(5) == "Ref($close, -6)/Ref($close, -1) - 1"
    # A steady IC of 0.03 with dispersion 0.1 over 250 days: ICIR 0.3, t 4.7; at a 5-day horizon the same
    # series has a fifth of the independent observations, t 2.1.
    rng = np.random.default_rng(1)
    series = pd.Series(0.03 + 0.1 * rng.standard_normal(250))
    one, five = stats(series, 1), stats(series, 5)
    assert one["t"] == pytest.approx(one["ir"] * np.sqrt(250)) and five["t"] == pytest.approx(one["t"] / np.sqrt(5))
    assert stats(pd.Series([], dtype=float)) is None
    horizons = [{"days": 1, "rank_ic": {"t": 1.2}}, {"days": 10, "rank_ic": {"t": -3.4}}, {"days": 20, "rank_ic": None}]
    assert verdict(horizons) == {"best_horizon": 10, "t": 3.4, "level": "signal"}
    assert verdict([{"days": 1, "rank_ic": {"t": 2.2}}])["level"] == "weak" and verdict([{"days": 1, "rank_ic": {"t": 0.5}}])["level"] == "noise"
    assert verdict([]) is None and T_SIGNAL == 3.0
    # Residualising strips the market (intercept) and the size slope; a label that is pure size leaves nothing.
    days = pd.to_datetime(["2025-01-02", "2025-01-03"])
    stocks = [f"S{i}" for i in range(12)]
    index = pd.MultiIndex.from_product([days, stocks], names=["datetime", "instrument"])
    size = pd.Series([float(2 ** i) for i in range(12)] * 2, index=index)
    label = pd.Series([0.01 + 0.002 * i for i in range(12)] + [-0.02 + 0.001 * i for i in range(12)], index=index)
    residual = residualize(label, size)
    assert residual.abs().max() < 1e-9
    noisy = label + pd.Series([(-1) ** i * 0.005 for i in range(24)], index=index)
    residual = residualize(noisy, size)
    assert residual.groupby(level="datetime").mean().abs().max() < 1e-9 and residual.abs().max() > 0.003


@pytest.mark.offline
def test_validate_config_accepts_horizon_and_rebalance() -> None:
    assert validate_config(_config())["horizon"] == 1 and validate_config(_config())["rebalance"] == 1
    config = validate_config(_config(horizon=5, rebalance=5))
    assert config["horizon"] == 5 and config["rebalance"] == 5
    assert validate_config(_config(horizon=None))["horizon"] == 1
    for bad in ({"horizon": 0}, {"horizon": 21}, {"rebalance": 2.5}, {"rebalance": "weekly"}):
        with pytest.raises((ValueError, TypeError)):
            validate_config(_config(**bad))


@pytest.mark.offline
def test_hold_scores_repeats_each_blocks_first_day() -> None:
    from rdagent.log.server.studio_worker import hold_scores

    days = pd.bdate_range("2025-01-06", periods=7)
    index = pd.MultiIndex.from_product([days, ["A", "B"]], names=["datetime", "instrument"])
    score = pd.Series(range(14), index=index, dtype=float)
    held = hold_scores(score, 5)
    assert held.xs(days[4], level="datetime").tolist() == [0.0, 1.0]   # inside the first block: day one's scores
    assert held.xs(days[5], level="datetime").tolist() == [10.0, 11.0]  # the second block starts fresh
    assert held.xs(days[6], level="datetime").tolist() == [10.0, 11.0]
    assert hold_scores(score, 1) is score


@pytest.mark.offline
def test_backtest_list_carries_total_return(studio_client, tmp_path: Path) -> None:
    folder = tmp_path / "traces" / "studio_backtests" / "11111111-1111-1111-1111-111111111111"
    folder.mkdir(parents=True)
    (folder / "config.json").write_text(json.dumps({"factors": [], "start": "2025-01-01", "end": "2025-06-30"}))
    (folder / "result.json").write_text(json.dumps({"status": "completed", "metrics": {"total_return": 0.05}}))
    job = studio_client.get("/studio/backtests").get_json()[0]
    assert job["total_return"] == 0.05


@pytest.mark.offline
def test_trace_status_distinguishes_unknown_and_loaded(studio_client) -> None:
    assert studio_client.get("/studio/trace-status", query_string={"trace": "nope/none"}).get_json() == {"loaded": False, "alive": False, "messages": 0}
    status = studio_client.get("/studio/trace-status", query_string={"trace": "Finance Data Building/demo"}).get_json()
    assert status["loaded"] is True and status["alive"] is False and status["messages"] >= 2


@pytest.mark.offline
def test_opencode_gateway_provider_resolves_to_its_fixed_base(studio_client, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from rdagent.log.server import studio_llm

    saved = studio_client.put("/studio/llm", json={"provider": "opencode", "model": "deepseek-v4-pro", "api_key": "oc-abcdefgh"}).get_json()
    assert saved["current"]["provider"] == "opencode" and saved["current"]["base_url"] == ""  # nothing typed: the gateway's own address is used
    r = studio_llm.resolve()
    assert r["model"] == "openai/deepseek-v4-pro" and r["base_url"] == "https://opencode.ai/zen/go/v1" and r["api_key"] == "oc-abcdefgh"
    env = studio_llm.env()
    assert env["CHAT_MODEL"] == "openai/deepseek-v4-pro" and env["OPENAI_API_KEY"] == "oc-abcdefgh"
    assert env["OPENAI_API_BASE"] == env["OPENAI_BASE_URL"] == "https://opencode.ai/zen/go/v1"
    # A mirror address still wins over the gateway default.
    assert studio_llm.resolve({"provider": "opencode", "model": "kimi-k3", "base_url": "https://mirror.example/v1"})["base_url"] == "https://mirror.example/v1"
    providers = {p["id"]: p for p in studio_client.get("/studio/llm").get_json()["providers"]}
    assert "muse-spark-1.3-contributor" in providers["opencode"]["models"] and not providers["opencode"].get("needs_base")
    # The gateway routes on a session header: every run gets a fresh id, carried to the research process as
    # LITELLM_EXTRA_HEADERS and sent with the connection test.
    import re, sys, types

    headers = json.loads(env["LITELLM_EXTRA_HEADERS"])
    assert headers["User-Agent"] == "rd-agent-studio/1.0" and re.fullmatch(r"[0-9a-f]{32}", headers["x-opencode-session"])
    assert json.loads(studio_llm.env()["LITELLM_EXTRA_HEADERS"])["x-opencode-session"] != headers["x-opencode-session"]
    assert studio_llm.resolve({"provider": "deepseek", "model": "deepseek-flash"})["headers"] == {}
    sent = {}
    fake = types.SimpleNamespace(completion=lambda **kw: sent.update(kw) or types.SimpleNamespace(choices=[types.SimpleNamespace(message=types.SimpleNamespace(content="OK"))]))
    monkeypatch.setitem(sys.modules, "litellm", fake)
    assert studio_llm.test_connection({"provider": "opencode", "model": "kimi-k3"})["ok"] is True
    assert sent["extra_headers"]["x-opencode-session"] and sent["api_base"] == "https://opencode.ai/zen/go/v1"
    # Each model lives on one of the gateway's three wire formats: the OpenAI-house models go through
    # LiteLLM's Responses bridge, MiniMax / Qwen through the Anthropic-format endpoint (named in full so
    # LiteLLM does not append /v1/messages to a path already ending in /v1), everything else stays on chat.
    muse = studio_llm.resolve({"provider": "opencode", "model": "muse-spark-1.3-contributor"})
    assert muse["model"] == "openai/responses/muse-spark-1.3-contributor" and muse["base_url"] == "https://opencode.ai/zen/go/v1"
    qwen = studio_llm.resolve({"provider": "opencode", "model": "qwen3.8-max"})
    assert qwen["model"] == "anthropic/qwen3.8-max" and qwen["base_url"] == "https://opencode.ai/zen/go/v1/messages"
    assert (qwen["key_env"], qwen["base_env"]) == ("ANTHROPIC_API_KEY", "ANTHROPIC_API_BASE")
    assert studio_llm.resolve({"provider": "opencode", "model": "kimi-k3"})["model"] == "openai/kimi-k3"
    studio_client.put("/studio/llm", json={"provider": "opencode", "model": "minimax-m3", "api_key": "oc-abcdefgh"})
    env = studio_llm.env()
    assert env["CHAT_MODEL"] == "anthropic/minimax-m3" and env["ANTHROPIC_API_KEY"] == "oc-abcdefgh"
    assert env["ANTHROPIC_API_BASE"] == "https://opencode.ai/zen/go/v1/messages" and "OPENAI_BASE_URL" not in env


@pytest.mark.offline
def test_llm_settings_save_env_and_test(studio_client, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import sys
    import types
    from rdagent.log.server import studio_llm

    monkeypatch.setattr(studio_llm, "_settings_path", tmp_path / "llm.json")
    monkeypatch.setenv("CHAT_MODEL", "deepseek/deepseek-chat")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-env-12345678")
    # Nothing saved yet: the UI sees what .env gave the server, without the key itself.
    current = studio_client.get("/studio/llm").get_json()["current"]
    assert current["source"] == "env" and current["provider"] == "deepseek" and current["model"] == "deepseek-chat"
    assert current["has_key"] and current["key_hint"] == "…5678" and "sk-env" not in json.dumps(current)
    assert studio_llm.env() == {}
    # Validation.
    assert studio_client.put("/studio/llm", json={"provider": "nope", "model": "x"}).status_code == 400
    assert "Base URL" in studio_client.put("/studio/llm", json={"provider": "openai_compatible", "model": "x"}).get_json()["error"]
    # Saving a provider with a key; the key file is private and the key never comes back.
    saved = studio_client.put("/studio/llm", json={"provider": "anthropic", "model": "claude-sonnet-5", "api_key": "sk-ant-abcdefgh", "max_retry": 5}).get_json()
    assert saved["current"] == {**saved["current"], "source": "studio", "provider": "anthropic", "key_hint": "…efgh", "has_key": True, "max_retry": 5}
    assert "sk-ant" not in json.dumps(saved)
    assert oct((tmp_path / "llm.json").stat().st_mode & 0o777) == "0o600"
    env = studio_llm.env()
    assert env["CHAT_MODEL"] == env["LITELLM_CHAT_MODEL"] == "anthropic/claude-sonnet-5"
    assert env["ANTHROPIC_API_KEY"] == "sk-ant-abcdefgh" and env["MAX_RETRY"] == "5"
    # A new research task inherits it beneath its own variables.
    task = server.RDAgentTask("fin_factor", {}, str(tmp_path / "o.log"), str(tmp_path / "t"), "s", "n", create_process=False, env={"QLIB_FACTOR_MARKET": "csi500"})
    assert task.env["ANTHROPIC_API_KEY"] == "sk-ant-abcdefgh" and task.env["QLIB_FACTOR_MARKET"] == "csi500"
    # macOS runs train in-process (forked DataLoader workers segfault there) unless the run says otherwise.
    monkeypatch.setattr(server.sys, "platform", "darwin")
    task = server.RDAgentTask("fin_factor", {}, str(tmp_path / "o.log"), str(tmp_path / "t"), "s", "n", create_process=False, env={"QLIB_MODEL_N_JOBS": "4"})
    assert task.env["QLIB_MODEL_N_JOBS"] == "4" and task.env["QLIB_FACTOR_N_JOBS"] == "0"
    monkeypatch.setattr(server.sys, "platform", "linux")
    assert "QLIB_FACTOR_N_JOBS" not in server.RDAgentTask("fin_factor", {}, str(tmp_path / "o.log"), str(tmp_path / "t"), "s", "n", create_process=False).env
    # The research window configured for factor runs (QLIB_FACTOR_*) also drives model and joint runs, which
    # read QLIB_MODEL_* / QLIB_QUANT_* and would otherwise evaluate on RD-Agent's 2008–2020 defaults.
    monkeypatch.setenv("QLIB_FACTOR_TRAIN_START", "2023-01-01")
    monkeypatch.setenv("QLIB_FACTOR_TEST_END", "2025-12-31")
    monkeypatch.delenv("QLIB_FACTOR_VALID_START", raising=False)
    task = server.RDAgentTask("fin_model", {}, str(tmp_path / "o.log"), str(tmp_path / "t"), "s", "n", create_process=False, env={"QLIB_QUANT_TEST_END": "2024-12-31"})
    assert task.env["QLIB_MODEL_TRAIN_START"] == task.env["QLIB_QUANT_TRAIN_START"] == "2023-01-01"
    assert task.env["QLIB_MODEL_TEST_END"] == "2025-12-31" and task.env["QLIB_QUANT_TEST_END"] == "2024-12-31"  # an explicit value wins
    assert "QLIB_MODEL_VALID_START" not in task.env
    # Switching provider without a key keeps the other provider's key on file and reports no key for the new one.
    switched = studio_client.put("/studio/llm", json={"provider": "openai", "model": "gpt-5"}).get_json()["current"]
    assert switched["has_key"] is False and switched["saved_keys"] == {"anthropic": "…efgh"}
    # Back on the .env provider without a stored key: the inherited key still counts, and is flagged as such.
    back = studio_client.put("/studio/llm", json={"provider": "deepseek", "model": "deepseek-chat"}).get_json()["current"]
    assert back["has_key"] and back["key_from_env"] and back["key_hint"] == "…5678"
    assert studio_llm.env()["DEEPSEEK_API_KEY"] == "sk-env-12345678"
    studio_client.put("/studio/llm", json={"provider": "openai", "model": "gpt-5"})
    assert studio_client.get("/studio/environment").get_json()["chat_model"] == "openai/gpt-5"
    # The connection test uses the form's key over the stored one and reports the model it called.
    calls = []

    def fake_completion(**kwargs):
        calls.append(kwargs)
        return types.SimpleNamespace(choices=[types.SimpleNamespace(message=types.SimpleNamespace(content="OK"))])

    monkeypatch.setitem(sys.modules, "litellm", types.SimpleNamespace(completion=fake_completion))
    result = studio_client.post("/studio/llm/test", json={"provider": "openai_compatible", "model": "qwen-plus", "api_key": "k1", "base_url": "https://x/v1"}).get_json()
    assert result["ok"] and result["reply"] == "OK" and result["model"] == "openai/qwen-plus"
    assert calls[0]["api_key"] == "k1" and calls[0]["api_base"] == "https://x/v1"
    assert studio_client.post("/studio/llm/test", json={"provider": "openai", "model": "gpt-5"}).status_code == 502


@pytest.mark.offline
def test_embedding_settings_share_keys_and_reach_the_run(studio_client, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import io
    import sys
    import types
    from rdagent.log.server import studio_llm

    monkeypatch.setattr(studio_llm, "_settings_path", tmp_path / "llm.json")
    for var in ("OPENAI_API_KEY", "EMBEDDING_MODEL", "LITELLM_EMBEDDING_MODEL", "DASHSCOPE_API_KEY", "GEMINI_API_KEY"):
        monkeypatch.delenv(var, raising=False)
    # DeepSeek chat saved; nothing embeds yet: the UI sees an unconfigured embedding and the run gets no model.
    studio_client.put("/studio/llm", json={"provider": "deepseek", "model": "deepseek-flash", "api_key": "sk-ds-12345678"})
    status = studio_client.get("/studio/llm").get_json()
    assert status["embedding"]["provider"] is None and not status["embedding"]["has_key"]
    assert [p["id"] for p in status["providers"] if p["embeddings"]] == ["openai", "gemini", "dashscope", "ollama"]
    assert studio_client.get("/studio/environment").get_json()["embedding_model"] == ""
    assert "EMBEDDING_MODEL" not in studio_llm.env()
    # Chat-only providers are refused; a provider with embeddings is saved with its own key.
    assert "没有嵌入接口" in studio_client.put("/studio/llm/embedding", json={"provider": "deepseek", "model": "x"}).get_json()["error"]
    saved = studio_client.put("/studio/llm/embedding", json={"provider": "dashscope", "model": "text-embedding-v4", "api_key": "sk-ali-abcdefgh"}).get_json()
    assert saved["embedding"] == {**saved["embedding"], "provider": "dashscope", "model": "text-embedding-v4", "key_hint": "…efgh", "has_key": True, "source": "studio"}
    assert saved["current"]["provider"] == "deepseek" and saved["current"]["saved_keys"] == {"deepseek": "…5678", "dashscope": "…efgh"}
    env = studio_llm.env()
    assert env["EMBEDDING_MODEL"] == env["LITELLM_EMBEDDING_MODEL"] == "dashscope/text-embedding-v4"
    assert env["DASHSCOPE_API_KEY"] == "sk-ali-abcdefgh" and env["DEEPSEEK_API_KEY"] == "sk-ds-12345678"
    assert studio_client.get("/studio/environment").get_json()["embedding_model"] == "dashscope/text-embedding-v4"
    # Switching chat to OpenAI reuses the OpenAI key for embeddings without a second entry.
    studio_client.put("/studio/llm", json={"provider": "openai", "model": "gpt-6-astra", "api_key": "sk-oa-11112222"})
    e = studio_client.put("/studio/llm/embedding", json={"provider": "openai", "model": "text-embedding-3-small"}).get_json()["embedding"]
    assert e["has_key"] and e["key_hint"] == "…2222"
    # A compatible endpoint for embeddings while chat is OpenAI would fight over OPENAI_API_BASE: refused.
    clash = studio_client.put("/studio/llm/embedding", json={"provider": "openai_compatible", "model": "BAAI/bge-m3", "base_url": "https://api.siliconflow.cn/v1", "api_key": "sf"})
    assert clash.status_code == 400 and "OPENAI_API_KEY" in clash.get_json()["error"]
    # Ollama needs no key; the model gets the provider prefix even when it carries a slash of its own.
    e = studio_client.put("/studio/llm/embedding", json={"provider": "ollama", "model": "nomic-embed-text"}).get_json()["embedding"]
    assert e["has_key"] and e["key_hint"] == ""
    assert studio_llm.env()["EMBEDDING_MODEL"] == "ollama/nomic-embed-text"
    studio_client.put("/studio/llm", json={"provider": "openai_compatible", "model": "qwen-plus", "base_url": "https://api.siliconflow.cn/v1", "api_key": "sf-1234567890"})
    e = studio_client.put("/studio/llm/embedding", json={"provider": "openai_compatible", "model": "BAAI/bge-m3", "base_url": "https://api.siliconflow.cn/v1"}).get_json()["embedding"]
    assert e["has_key"] and studio_llm.env()["EMBEDDING_MODEL"] == "openai/BAAI/bge-m3"
    # The embedding test calls litellm.embedding with the form's key and reports the vector size.
    calls = []

    def fake_embedding(**kwargs):
        calls.append(kwargs)
        return types.SimpleNamespace(data=[{"embedding": [0.1, 0.2, 0.3]}])

    monkeypatch.setitem(sys.modules, "litellm", types.SimpleNamespace(embedding=fake_embedding))
    result = studio_client.post("/studio/llm/embedding/test", json={"provider": "gemini", "model": "gemini-embedding-001", "api_key": "g1"}).get_json()
    assert result["ok"] and result["dims"] == 3 and result["model"] == "gemini/gemini-embedding-001" and calls[0]["api_key"] == "g1"
    assert studio_client.post("/studio/llm/embedding/test", json={"provider": "gemini", "model": "gemini-embedding-001"}).status_code == 502
    # A key with stray non-ASCII characters (a pasted hint, full-width letters) is named instead of a codec error.
    bad = studio_client.post("/studio/llm/embedding/test", json={"provider": "gemini", "model": "gemini-embedding-001", "api_key": "sk-abc 已保存…"}).get_json()
    assert not bad["ok"] and "非 ASCII" in bad["error"] and "第 8 位" in bad["error"]
    assert "非 ASCII" in studio_client.put("/studio/llm/embedding", json={"provider": "gemini", "model": "x", "api_key": "ｓｋ-full-width"}).get_json()["error"]
    assert "非 ASCII" in studio_client.put("/studio/llm", json={"provider": "openai", "model": "x", "base_url": "https://中转.example/v1"}).get_json()["error"]
    # Clearing the record removes it and leaves the keys alone.
    cleared = studio_client.put("/studio/llm/embedding", json={"provider": ""}).get_json()
    assert cleared["embedding"]["provider"] is None and "dashscope" in cleared["current"]["saved_keys"]
    # Listing embedding models keeps the embedding ids (and, for Gemini, the embedContent models).
    class FakeResponse(io.BytesIO):
        def __enter__(self): return self
        def __exit__(self, *a): return False

    def fake_urlopen(req, timeout=20):
        if "googleapis" in req.full_url:
            body = {"models": [{"name": "models/gemini-3.8-flash", "supportedGenerationMethods": ["generateContent"]},
                               {"name": "models/gemini-embedding-001", "supportedGenerationMethods": ["embedContent"]}]}
        elif "11434" in req.full_url:
            body = {"models": [{"name": "nomic-embed-text:latest"}, {"name": "qwen3:8b"}]}
        else:
            body = {"data": [{"id": "gpt-6-astra"}, {"id": "text-embedding-3-large"}, {"id": "text-embedding-3-small"}]}
        return FakeResponse(json.dumps(body).encode())

    monkeypatch.setattr(studio_llm.urllib.request, "urlopen", fake_urlopen)
    assert studio_client.post("/studio/llm/models", json={"provider": "openai", "api_key": "k", "kind": "embedding"}).get_json()["models"] == ["text-embedding-3-small", "text-embedding-3-large"]
    assert studio_client.post("/studio/llm/models", json={"provider": "gemini", "api_key": "g", "kind": "embedding"}).get_json()["models"] == ["gemini-embedding-001"]
    assert studio_client.post("/studio/llm/models", json={"provider": "ollama", "kind": "embedding"}).get_json()["models"] == ["nomic-embed-text:latest"]


@pytest.mark.offline
def test_llm_model_listing_filters_chat_models(studio_client, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import io
    from rdagent.log.server import studio_llm

    monkeypatch.setattr(studio_llm, "_settings_path", tmp_path / "llm.json")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    seen = {}

    class FakeResponse(io.BytesIO):
        def __enter__(self): return self
        def __exit__(self, *a): return False

    def fake_urlopen(req, timeout=20):
        seen["url"] = req.full_url; seen["headers"] = dict(req.header_items())
        if "googleapis" in req.full_url:
            body = {"models": [{"name": "models/gemini-3.8-flash", "supportedGenerationMethods": ["generateContent"]},
                               {"name": "models/embedding-001", "supportedGenerationMethods": ["embedContent"]}]}
        else:
            body = {"data": [{"id": "gpt-5.6-sol"}, {"id": "text-embedding-3-small"}, {"id": "whisper-1"}, {"id": "gpt-6-astra"}]}
        return FakeResponse(json.dumps(body).encode())

    monkeypatch.setattr(studio_llm.urllib.request, "urlopen", fake_urlopen)
    assert "API Key" in studio_client.post("/studio/llm/models", json={"provider": "openai"}).get_json()["error"]
    result = studio_client.post("/studio/llm/models", json={"provider": "openai", "api_key": "k"}).get_json()
    assert result["ok"] and result["models"] == ["gpt-6-astra", "gpt-5.6-sol"]
    assert seen["headers"]["Authorization"] == "Bearer k" and seen["url"] == "https://api.openai.com/v1/models"
    result = studio_client.post("/studio/llm/models", json={"provider": "gemini", "api_key": "g"}).get_json()
    assert result["models"] == ["gemini-3.8-flash"] and "key=g" in seen["url"] and "key" not in result["source"]
    result = studio_client.post("/studio/llm/models", json={"provider": "openai_compatible", "api_key": "k", "base_url": "https://relay/v1/"}).get_json()
    assert result["ok"] and seen["url"] == "https://relay/v1/models"


@pytest.mark.offline
def test_sync_remote_check_falls_back_when_the_api_is_rate_limited(monkeypatch: pytest.MonkeyPatch) -> None:
    import urllib.error
    from rdagent.log.server import studio_sync

    monkeypatch.setattr(studio_sync, "_remote_cache", {"checked_at": 0.0, "release": None})

    def limited(url, timeout=20):
        raise urllib.error.HTTPError(url, 403, "rate limit exceeded", {}, None)

    monkeypatch.setattr(studio_sync, "_get_json", limited)
    monkeypatch.setattr(studio_sync, "_latest_tag_by_redirect", lambda timeout=20: "2026-09-15")
    release = studio_sync.check_remote(max_age=0)
    assert release["release"] == "2026-09-15" and release["archive_bytes"] is None
    assert release["archive_url"] == f"https://github.com/{studio_sync.REPO}/releases/download/2026-09-15/{studio_sync.ARCHIVE}"
    # Both routes down: the cached answer is served; with no cache the error names the rate limit.
    monkeypatch.setattr(studio_sync, "_latest_tag_by_redirect", lambda timeout=20: (_ for _ in ()).throw(RuntimeError("offline")))
    assert studio_sync.check_remote(max_age=0)["release"] == "2026-09-15"
    monkeypatch.setattr(studio_sync, "_remote_cache", {"checked_at": 0.0, "release": None})
    with pytest.raises(RuntimeError, match="限流"):
        studio_sync.check_remote(max_age=0)
    # Other HTTP errors still surface as they are.
    monkeypatch.setattr(studio_sync, "_get_json", lambda url, timeout=20: (_ for _ in ()).throw(urllib.error.HTTPError(url, 500, "boom", {}, None)))
    with pytest.raises(urllib.error.HTTPError):
        studio_sync.check_remote(max_age=0)


@pytest.mark.offline
def test_backtest_on_a_us_universe_takes_its_data_region_and_rules(studio_client, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    cn = tmp_path / "qlib_data" / "cn_data"
    (cn / "instruments").mkdir(parents=True)
    (cn / "instruments" / "csi300.txt").write_text("SH600000\t2020-01-01\t2030-01-01\n")
    us = tmp_path / "qlib_data" / "us_ndx"
    (us / "instruments").mkdir(parents=True)
    (us / "calendars").mkdir()
    (us / "calendars" / "day.txt").write_text("2025-01-02\n")
    (us / "instruments" / "nasdaq100.txt").write_text("AAPL\t2020-01-01\t2030-01-01\n")
    (us / "studio-universe.json").write_text(json.dumps({"region": "us", "label": "美股", "benchmark": "^ndx", "markets": {"nasdaq100": "纳斯达克 100"}}))
    monkeypatch.setenv("QLIB_PROVIDER_URI", str(cn))
    body = {"trace": "Finance Data Building/demo", "loop_id": 0, "factors": [{"name": "STR_5", "weight": 1}],
            "start": "2025-01-01", "end": "2025-06-30", "market": "nasdaq100",
            "topk": 10, "n_drop": 2, "account": 1000000, "open_cost": 0.0005, "close_cost": 0.0015}
    response = studio_client.post("/studio/backtests", json=body)
    assert response.status_code == 202, response.get_json()
    config = json.loads((tmp_path / "traces" / "studio_backtests" / response.get_json()["id"] / "config.json").read_text())
    assert config["provider_uri"] == str(us) and config["region"] == "us"
    assert config["benchmark"] == "^ndx" and config["limit_threshold"] is None and config["min_cost"] == 1
    # Commissions given by the caller are kept; a body without them gets the market's defaults.
    assert config["open_cost"] == 0.0005 and config["close_cost"] == 0.0015
    slim = {k: v for k, v in body.items() if k not in ("open_cost", "close_cost")}
    job = studio_client.post("/studio/backtests", json=slim).get_json()["id"]
    defaults = json.loads((tmp_path / "traces" / "studio_backtests" / job / "config.json").read_text())
    assert defaults["open_cost"] == 0.0001 and defaults["close_cost"] == 0.0001
    assert studio_client.post("/studio/backtests", json=dict(body, market="sp500")).status_code == 400


@pytest.mark.offline
def test_lists_are_scoped_by_region(studio_client, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    cn = tmp_path / "qlib_data" / "cn_data"
    (cn / "instruments").mkdir(parents=True)
    (cn / "calendars").mkdir()
    (cn / "calendars" / "day.txt").write_text("2025-01-02\n2025-06-30\n")
    (cn / "instruments" / "csi300.txt").write_text("SH600000\t2020-01-01\t2030-01-01\n")
    us = tmp_path / "qlib_data" / "us_ndx"
    (us / "instruments").mkdir(parents=True)
    (us / "calendars").mkdir()
    (us / "calendars" / "day.txt").write_text("2007-01-03\n2026-09-15\n")
    (us / "instruments" / "nasdaq100.txt").write_text("AAPL\t2020-01-01\t2030-01-01\n")
    (us / "studio-universe.json").write_text(json.dumps({"region": "us", "benchmark": "^ndx", "markets": {"nasdaq100": "纳斯达克 100"}}))
    (us / "instrument_names.json").write_text(json.dumps({"source": "nasdaq", "names": {"AAPL": {"name": "APPLE INC."}}}))
    monkeypatch.setenv("QLIB_PROVIDER_URI", str(cn))
    trace_folder = server.app.config["LOG_FOLDER_PATH"]
    # A second experiment marked as a NASDAQ-100 run.
    task = server._get_or_create_task(str(trace_folder / "Finance Data Building/us-run"))
    task.messages = [{"tag": "research.hypothesis", "loop_id": "0", "timestamp": "2026-09-01T10:00:00", "content": {"hypothesis": "us"}}]
    (trace_folder / "Finance Data Building/us-run").mkdir(parents=True, exist_ok=True)
    (trace_folder / "Finance Data Building/us-run" / "studio-run.json").write_text(json.dumps({"market": "nasdaq100"}))
    ids = lambda rows: sorted(r["id"] for r in rows)  # noqa: E731
    assert ids(studio_client.get("/studio/experiments").get_json()) == ["Finance Data Building/demo", "Finance Data Building/us-run"]
    assert ids(studio_client.get("/studio/experiments?region=us").get_json()) == ["Finance Data Building/us-run"]
    assert ids(studio_client.get("/studio/experiments?region=cn").get_json()) == ["Finance Data Building/demo"]
    # Factors follow their experiment's market; the demo factor is an A-share one.
    assert [f["name"] for f in studio_client.get("/studio/factors?region=cn").get_json()] == ["STR_5"]
    assert studio_client.get("/studio/factors?region=us").get_json() == []
    # Backtests are scoped by their config's market.
    for market in ("csi300", "nasdaq100"):
        body = {"trace": "Finance Data Building/demo", "loop_id": 0, "factors": [{"name": "STR_5", "weight": 1}],
                "start": "2025-01-03", "end": "2025-06-30", "market": market, "topk": 10, "n_drop": 2, "account": 1000000, "open_cost": 0.0005, "close_cost": 0.0015}
        assert studio_client.post("/studio/backtests", json=body).status_code == 202
    assert [j["config"]["market"] for j in studio_client.get("/studio/backtests?region=us").get_json()] == ["nasdaq100"]
    assert [j["config"]["market"] for j in studio_client.get("/studio/backtests?region=cn").get_json()] == ["csi300"]
    assert len(studio_client.get("/studio/backtests").get_json()) == 2
    # Workspaces, per-region environment and names.
    regions = {r["region"]: r for r in studio_client.get("/studio/regions").get_json()}
    assert regions["cn"]["ready"] and regions["us"]["ready"] and regions["us"]["end"] == "2026-09-15" and regions["us"]["markets"] == ["nasdaq100"]
    env = studio_client.get("/studio/environment?region=us").get_json()
    assert env["provider_uri"] == str(us) and env["start"] == "2007-01-03"
    assert studio_client.get("/studio/environment").get_json()["end"] == "2025-06-30"
    assert studio_client.get("/studio/instruments/names?region=us").get_json()["names"]["AAPL"]["name"] == "APPLE INC."
    assert studio_client.get("/studio/instruments/names").get_json()["names"] == {}
    # Without any US data the workspace is still listed, not ready.
    (us / "studio-universe.json").unlink()
    regions = {r["region"]: r for r in studio_client.get("/studio/regions").get_json()}
    assert regions["us"]["ready"] is False and regions["us"]["markets"] == []


@pytest.mark.offline
def test_trace_ids_are_scoped_by_region(studio_client, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    cn = tmp_path / "qlib_data" / "cn_data"
    (cn / "instruments").mkdir(parents=True)
    (cn / "instruments" / "csi300.txt").write_text("SH600000\t2020-01-01\t2030-01-01\n")
    us = tmp_path / "qlib_data" / "us_ndx"
    (us / "instruments").mkdir(parents=True)
    (us / "instruments" / "nasdaq100.txt").write_text("AAPL\t2020-01-01\t2030-01-01\n")
    (us / "studio-universe.json").write_text(json.dumps({"region": "us", "benchmark": "^ndx", "markets": {"nasdaq100": "纳斯达克 100"}}))
    monkeypatch.setenv("QLIB_PROVIDER_URI", str(cn))
    root = server.app.config["LOG_FOLDER_PATH"]
    for name, market in (("us-run", "nasdaq100"), ("cn-run", "csi300"), ("old-run", None)):
        folder = root / "Finance Data Building" / name
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "debug_tpl").mkdir(exist_ok=True)
        (folder / "debug_tpl" / "x.pkl").write_bytes(b"")  # what marks a folder as a trace
        if market:
            (folder / "studio-run.json").write_text(json.dumps({"market": market}))
    every = set(studio_client.get("/traces").get_json())
    assert {"Finance Data Building/us-run", "Finance Data Building/cn-run", "Finance Data Building/old-run"} <= every
    assert studio_client.get("/traces?region=us").get_json() == ["Finance Data Building/us-run"]
    cn_ids = set(studio_client.get("/traces?region=cn").get_json())
    assert "Finance Data Building/us-run" not in cn_ids and {"Finance Data Building/cn-run", "Finance Data Building/old-run"} <= cn_ids


@pytest.mark.offline
def test_trace_tail_returns_cleaned_last_lines(studio_client) -> None:
    root = server.app.config["LOG_FOLDER_PATH"]
    (root / "Finance Data Building").mkdir(parents=True, exist_ok=True)
    log = root / "Finance Data Building" / "demo.log"
    log.write_text(
        "2026-09-16 22:33:08.455 | INFO     | rdagent.utils.workflow.loop:_run_step:216 - Start Loop 0, Step 3: feedback\n"
        "2026/09/16 22:32:54 INFO mlflow.agent.hint: Load the \n"
        "Workflow Progress:  60%|██████    | 3/5 [03:12<02:08, 64.21s/step]\n"
        "\x1b[32mUsing chat model\x1b[0m deepseek/deepseek-flash\n"
        "Training until validation scores don't improve for 50 rounds\n"
    )
    payload = studio_client.get("/studio/trace-tail", query_string={"trace": "Finance Data Building/demo", "lines": 3}).get_json()
    assert payload["lines"] == ["22:33:08 Start Loop 0, Step 3: feedback", "Using chat model deepseek/deepseek-flash", "Training until validation scores don't improve for 50 rounds"]
    assert payload["updated"] and payload["size"] > 0
    assert studio_client.get("/studio/trace-tail", query_string={"trace": "Finance Data Building/nothing"}).get_json()["lines"] == []
    # A continued run's .resume.log is newer than the original log and is the one shown.
    import os, time
    resume = studio_module.TRACE_ROOT / "Finance Data Building" / "demo.resume.log"
    resume.write_text("12:00:00 Start Loop 3, Step 0: direct_exp_gen\n")
    future = time.time() + 5
    os.utime(resume, (future, future))
    assert studio_client.get("/studio/trace-tail", query_string={"trace": "Finance Data Building/demo", "lines": 3}).get_json()["lines"][-1].startswith("12:00:00 Start Loop 3")
    assert studio_client.get("/studio/trace-tail", query_string={"trace": "../etc"}).status_code == 400


@pytest.mark.offline
def test_attention_lists_unanswered_requests_of_live_runs(studio_client) -> None:
    trace_folder = server.app.config["LOG_FOLDER_PATH"]
    task = server._get_or_create_task(str(trace_folder / "Finance Data Building/waiting"))
    task.messages = [
        {"tag": "research.hypothesis", "loop_id": "0", "timestamp": "2026-09-17T01:00:00", "content": {"hypothesis": "h"}},
        {"tag": "user_interaction.request", "timestamp": "2026-09-17T01:00:05", "content": {"hypothesis": "h", "reason": "r"}},
    ]
    # Not alive: nothing pending.
    assert studio_client.get("/studio/attention").get_json() == []
    task.is_alive = lambda: True  # type: ignore[method-assign]
    task.process = object()  # type: ignore[assignment]
    items = studio_client.get("/studio/attention").get_json()
    assert items == [{"trace": "Finance Data Building/waiting", "market": "csi300", "kind": "hypothesis", "since": "2026-09-17T01:00:05", "round": 1}]
    assert studio_client.get("/studio/attention?region=us").get_json() == []
    summary = next(e for e in studio_client.get("/studio/experiments").get_json() if e["id"].endswith("waiting"))
    assert summary["waiting"] == "hypothesis"
    # Answering marks it done even before the process emits anything new.
    task.user_response_q = type("Q", (), {"put": lambda self, *a, **k: None})()
    assert studio_client.post("/user_interaction/submit", json={"id": "Finance Data Building/waiting", "payload": {"hypothesis": "h"}}).status_code == 200
    assert studio_client.get("/studio/attention").get_json() == []
    # A feedback request is classified as such, and stays pending even when log events arrive after it.
    task.messages.append({"tag": "user_interaction.request", "timestamp": "2026-09-17T01:20:00", "content": {"decision": True, "reason": "ok"}})
    task.messages.append({"tag": "research.hypothesis", "loop_id": "1", "timestamp": "2026-09-17T01:20:01", "content": {"hypothesis": "late"}})
    assert studio_client.get("/studio/attention").get_json()[0]["kind"] == "feedback"
    # Submitting twice: the second is refused instead of queueing a stray payload.
    assert studio_client.post("/user_interaction/submit", json={"id": "Finance Data Building/waiting", "payload": {"decision": True}}).status_code == 200
    assert studio_client.post("/user_interaction/submit", json={"id": "Finance Data Building/waiting", "payload": {"decision": True}}).status_code == 409


@pytest.mark.offline
def test_gate_judges_factors_by_t_duplication_and_replication() -> None:
    from rdagent.log.server import studio_gate

    def analysis(t, residual=True, horizon=5, ic=0.03):
        key = "residual_rank_ic" if residual else "rank_ic"
        return {"days": 400, "rank_ic": {"mean": 0.02, "ir": 0.1}, "horizons": [{"days": 1, key: {"t": t / 2, "mean": ic / 2}}, {"days": horizon, key: {"t": t, "mean": ic}}]}

    assert studio_gate.best_t(analysis(3.5)) == (3.5, 5)
    assert studio_gate.best_t({"days": 400, "rank_ic": {"mean": 0.02, "ir": 0.1}}) == (pytest.approx(2.0), 1)
    assert studio_gate.best_t({}) == (None, None)
    # Horizon-aware bars: a 20-day t of 2.2 clears its bar (2.0) while a 1-day t of 2.2 does not (3.0); the
    # horizon is chosen by how far |t| clears its own bar, not by raw |t|.
    long_run = {"days": 800, "horizons": [{"days": 1, "residual_rank_ic": {"t": 2.6, "mean": 0.01}}, {"days": 20, "residual_rank_ic": {"t": 2.2, "mean": 0.03}}]}
    assert studio_gate.best_stats(long_run) == (2.2, 20, 0.03)
    verdict20 = studio_gate.judge_factor("L", "/ws/L", "nasdaq100", [], analyze=lambda p, m: long_run, correlate=None, replicate=None)
    assert verdict20["level"] == "signal" and verdict20["horizon"] == 20
    short_only = {"days": 800, "horizons": [{"days": 1, "residual_rank_ic": {"t": 2.2, "mean": 0.03}}]}
    assert studio_gate.judge_factor("S", "/ws/S", "nasdaq100", [], analyze=lambda p, m: short_only, correlate=None, replicate=None)["level"] == "weak"
    analyses = {"NEW": analysis(4.0), "COPY": analysis(6.0), "WEAK": analysis(2.4), "DEAD": analysis(0.8), "LOCAL": analysis(-3.6), "TINY": analysis(5.0, ic=0.012)}
    others = {"csi1000": {"NEW": analysis(2.7), "LOCAL": analysis(0.3)}}
    corr = {"NEW": 0.31, "COPY": 0.92, "WEAK": 0.1, "DEAD": 0.0, "LOCAL": -0.55, "TINY": 0.2}

    def correlate(pairs):
        names = [n for n, _ in pairs]
        matrix = [[1.0 if a == b else corr.get(a, corr.get(b, 0.0)) for b in names] for a in names]
        return {"names": names, "matrix": matrix}

    library = [("RVOL_20", "/lib/rvol")]
    kw = {"analyze": lambda path, market: analyses[Path(path).name], "correlate": correlate, "replicate": lambda name, path, second: others[second][name]}
    gate = studio_gate.gate_round([(n, f"/ws/{n}") for n in analyses], "csi300", library, **kw)
    levels = {f["name"]: f["level"] for f in gate["factors"]}
    assert levels == {"NEW": "signal", "COPY": "duplicate", "WEAK": "weak", "DEAD": "noise", "LOCAL": "unreplicated", "TINY": "weak"}
    tiny = next(f for f in gate["factors"] if f["name"] == "TINY")
    assert tiny["ic"] == 0.012 and "量级不到 0.02" in "；".join(tiny["reasons"])  # real (t 5) but too small to pay for turnover
    assert gate["decision"] is True and gate["second_market"] == "csi1000"
    new = next(f for f in gate["factors"] if f["name"] == "NEW")
    assert new["t"] == 4.0 and new["horizon"] == 5 and new["ic"] == 0.03 and new["t2"] == 2.7 and new["replicated"] is True and new["corr"] == 0.31
    assert gate["thresholds"]["t_signal"] == {1: 3.0, 5: 2.5, 10: 2.0, 20: 2.0}
    local = next(f for f in gate["factors"] if f["name"] == "LOCAL")
    assert local["replicated"] is False and "增量有限" in "；".join(local["reasons"])
    assert "COPY ≈ RVOL_20" in gate["hint"] and "WEAK、DEAD" in gate["hint"] and "RVOL_20" in gate["hint"] and "通过" in gate["summary"]
    # Families and the full name list reach the hint; error-level factors are named as untested.
    gate2 = studio_gate.gate_round([("X", "/ws/X")], "csi300", library, analyze=lambda p, m: (_ for _ in ()).throw(RuntimeError("all NaN")), correlate=correlate, replicate=None,
                                   families=["RVOL_20", "ILLIQ_20"], existing=["ILLIQ_20", "RVOL_20", "MOM_20"])
    assert "各列一个代表；新假设与它们的相关要低于 0.5）：RVOL_20、ILLIQ_20" in gate2["hint"] and "库里已有 3 个因子" in gate2["hint"] and "没有产出可用的值" in gate2["hint"] and "X" in gate2["hint"]
    # Family representatives: strongest first, a factor is dropped when it correlates ≥ 0.7 with one already kept.
    lib = [("A", "/a"), ("B", "/b"), ("C", "/c")]
    fam_corr = {("A", "B"): 0.9, ("A", "C"): 0.2, ("B", "C"): 0.3}
    def correlate_lib(pairs):
        names = [n for n, _ in pairs]
        return {"names": names, "matrix": [[1.0 if a == b else fam_corr.get((a, b), fam_corr.get((b, a), 0.0)) for b in names] for a in names]}
    assert studio_gate.family_representatives(lib, correlate_lib) == ["A", "C"]
    assert studio_gate.family_representatives(lib, lambda pairs: (_ for _ in ()).throw(ValueError("no overlap"))) == ["A", "B", "C"]
    # Without a passing factor the round is rejected; an analysis failure is reported, not raised; a market without a second universe does no replication.
    gate = studio_gate.gate_round([("DEAD", "/ws/DEAD"), ("X", "/ws/X")], "other", [], analyze=lambda p, m: analyses.get(Path(p).name) or (_ for _ in ()).throw(RuntimeError("no result.h5")), correlate=correlate, replicate=None)
    assert gate["decision"] is False and [f["level"] for f in gate["factors"]] == ["noise", "error"] and gate["second_market"] is None
    assert studio_gate.SECOND_MARKET["us500"] == "usmid" and studio_gate.SECOND_MARKET["nasdaq100"] == "usmid"  # large caps replicate on the mid caps


@pytest.mark.offline
def test_feedback_requests_wait_for_the_gate_and_carry_its_verdict(studio_client, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    trace_folder = server.app.config["LOG_FOLDER_PATH"]
    task = server.rdagent_processes[str(trace_folder / "Finance Data Building/demo")]
    replies = []
    task.user_response_q = type("Q", (), {"put": lambda self, payload, **k: replies.append(payload)})()

    class FakeRequests:  # a multiprocessing queue hands items over asynchronously; the test needs them at once
        def __init__(self): self.items = []
        def put(self, item, **k): self.items.append(item)
        def get_nowait(self):
            if not self.items:
                raise server.Empty
            return self.items.pop(0)

    task.user_request_q = FakeRequests()
    task.is_alive = lambda: True  # type: ignore[method-assign]
    task.process = object()  # type: ignore[assignment]
    verdict = {"factors": [{"name": "STR_5", "level": "duplicate", "t": 5.0, "horizon": 1, "nearest": "RVOL_20", "corr": 0.9, "second_market": "csi1000", "t2": None, "replicated": None, "reasons": ["与库里的 RVOL_20 相关 +0.90"]}],
               "decision": False, "summary": "验收：不通过。STR_5：重复。", "hint": "不要再提波动率族", "market": "csi300", "second_market": "csi1000", "thresholds": {}}
    seen = []
    monkeypatch.setattr(server.studio_gate, "gate_round", lambda factors, market, library, **kw: seen.append((factors, market, library)) or dict(verdict))
    monkeypatch.setattr(server, "run_refresh", lambda *a, **k: None, raising=False)
    # Every REFLECT_EVERY gated rounds the memo is written with the configured model on the verdicts so far.
    prompts = []
    monkeypatch.setattr(server, "REFLECT_EVERY", 1)
    monkeypatch.setattr(server.studio_llm, "complete", lambda prompt, **kw: prompts.append(prompt) or "观察：波动率族已饱和。\n反思：…\n方向：换成交额结构。")
    monkeypatch.setattr(server.studio_llm, "resolve", lambda values=None: {"model": "deepseek/deepseek-flash"})
    # The fixture's round 0 has a metric event with STR_5's workspace and no verdict yet: that is the round under judgement.
    task.user_request_q.put({"decision": True, "reason": "looks promising", "new_hypothesis": "more of the same", "observations": "", "hypothesis_evaluation": ""})
    server._drain_user_requests_into_messages(task)
    request_msg = server.latest_request(task)
    assert request_msg["gate"] == "pending"
    server.apply_confirm_policy(task)  # the policy would answer a verdict at once, but the gate is still running
    assert replies == []
    _wait_for(lambda: request_msg.get("gate") != "pending")
    assert seen and seen[0][0] == [("STR_5", str(tmp_path / "ws" / "f0"))] and seen[0][1] == "csi300"
    assert request_msg["content"]["decision"] is False
    assert request_msg["content"]["reason"].startswith("【验收】验收：不通过") and "【Agent 原判断】接受：looks promising" in request_msg["content"]["reason"]
    # The hint is rebuilt with the campaign memory: this round's verdicts, what the sample can certify, what
    # every market has judged, and the run's statistics so far.
    hint = request_msg["content"]["new_hypothesis"]
    assert hint.startswith("more of the same\n\n这些是库里已有信号的变体，不要再提类似的：STR_5 ≈ RVOL_20")
    assert "本股票池 csi300" in hint and "过验收线需要：1 日 ICIR ≥" in hint
    assert "本次研究至今 1 轮、1 个因子：重复 1；通过率 0%，重复率 100%" in hint
    assert hint.endswith("请提出机制不同的假设，而不是同一族的新参数。\n\n【反思备忘录（1 轮后，deepseek/deepseek-flash）】\n观察：波动率族已饱和。\n反思：…\n方向：换成交额结构。")
    assert len(prompts) == 1 and "第 1 轮：STR_5 重复（与库里的 RVOL_20 相关 +0.90）" in prompts[0] and "本股票池 csi300" in prompts[0]
    gate_event = [m for m in task.messages if m.get("tag") == "studio.gate"][-1]
    assert gate_event["content"]["context"] == request_msg["gate"]["context"] and len(request_msg["gate"]["context"]) >= 2
    memo_event = [m for m in task.messages if m.get("tag") == "studio.reflection"][-1]
    assert memo_event["loop_id"] == 0 and memo_event["content"]["rounds"] == 1
    assert memo_event["content"]["memo"].startswith("观察：") and memo_event["content"]["stats"]["duplicate_rate"] == 1.0
    assert [e["tag"] for e in server.studio_events(trace_folder / "Finance Data Building/demo")] == ["studio.gate", "studio.reflection"]
    assert request_msg["content"]["hypothesis_evaluation"].startswith("【验收】验收：不通过")  # survives in the replayed history
    assert gate_event["loop_id"] == 0 and gate_event["content"]["decision"] is False
    # The verdict is written beside the trace, so a reload of the trace from RD-Agent's log brings it back.
    persisted = server.studio_events(trace_folder / "Finance Data Building/demo")
    assert persisted[0]["tag"] == "studio.gate" and persisted[0]["content"]["summary"] == verdict["summary"]
    server.apply_confirm_policy(task)
    assert replies[-1]["decision"] is False and replies[-1]["new_hypothesis"] == hint
    # On demand, the memo is written again on the same verdicts.
    again = studio_client.post("/studio/research/reflect", json={"id": "Finance Data Building/demo"})
    assert again.status_code == 200 and again.get_json()["memo"].startswith("观察：") and len(prompts) == 2
    assert studio_client.post("/studio/research/reflect", json={"id": "Finance Data Building/nope"}).status_code == 404
    # Gate off: the request passes straight through.
    task.confirm = server.parse_confirm("auto", 0, gate=False)
    task.user_request_q.put({"decision": True, "reason": "r"})
    server._drain_user_requests_into_messages(task)
    assert "gate" not in server.latest_request(task)
    assert server.parse_confirm(None, None)["gate"] is True


@pytest.mark.offline
def test_confirm_policy_answers_requests_by_mode_and_timeout(studio_client, monkeypatch: pytest.MonkeyPatch) -> None:
    from datetime import datetime, timedelta, timezone

    trace_folder = server.app.config["LOG_FOLDER_PATH"]
    task = server._get_or_create_task(str(trace_folder / "Finance Data Building/policy"))
    replies = []
    task.user_response_q = type("Q", (), {"put": lambda self, payload, **k: replies.append(payload)})()
    task.is_alive = lambda: True  # type: ignore[method-assign]
    task.process = object()  # type: ignore[assignment]
    fresh = datetime.now(timezone.utc).isoformat()

    def request(content, ts=fresh):
        task.messages.append({"tag": "user_interaction.request", "timestamp": ts, "content": content})

    # Default policy (hypothesis only): instruction, features and verdicts pass as proposed, a hypothesis waits.
    task.confirm = server.parse_confirm(None, None, "focus on volume")
    request({"user_instruction": None})
    server.apply_confirm_policy(task)
    # The direction goes out with the campaign memory for the run's universe attached.
    assert replies[-1]["user_instruction"].startswith("focus on volume\n\n研究记忆（Studio 自动附上）：\n本股票池 csi300")
    assert task.messages[-1]["tag"] == "user_interaction.auto"
    task.confirm = server.parse_confirm(None, None, "focus on volume", gate=False)
    request({"user_instruction": None})
    server.apply_confirm_policy(task)
    assert replies[-1] == {"user_instruction": "focus on volume"}  # gate off: the direction alone
    task.confirm = server.parse_confirm(None, None, "focus on volume")
    request({"features": {"A": "$close"}, "feature_validation_msg": ""})
    server.apply_confirm_policy(task)
    assert replies[-1] == {"A": "$close"}
    request({"hypothesis": "h", "reason": "r"})
    server.apply_confirm_policy(task)
    assert len(replies) == 3 and task.messages[-1]["tag"] == "user_interaction.request"
    assert studio_client.get("/studio/attention").get_json()[0]["kind"] == "hypothesis"
    # ... until the timeout passes.
    task.messages[-1]["timestamp"] = (datetime.now(timezone.utc) - timedelta(minutes=31)).isoformat()
    server.apply_confirm_policy(task)
    assert replies[-1] == {"hypothesis": "h", "reason": "r"} and task.messages[-1]["content"] == {"kind": "hypothesis", "why": "timeout"}
    assert studio_client.get("/studio/attention").get_json() == []
    # "all" waits on everything and never times out with timeout 0; "auto" waits on nothing.
    task.confirm = server.parse_confirm("all", 0)
    request({"decision": True, "reason": "ok"}, (datetime.now(timezone.utc) - timedelta(hours=5)).isoformat())
    server.apply_confirm_policy(task)
    assert len(replies) == 4
    task.confirm = server.parse_confirm("auto", 0)
    server.apply_confirm_policy(task)
    assert replies[-1] == {"decision": True, "reason": "ok"}
    with pytest.raises(ValueError):
        server.parse_confirm("sometimes", 5)
    with pytest.raises(ValueError):
        server.parse_confirm("all", 5000)


@pytest.mark.offline
def test_upload_and_resume_carry_the_confirm_policy(studio_client, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(server, "upload_folder_path", tmp_path / "uploads")
    monkeypatch.setattr(server, "universe_env", lambda market, build=True: {})
    started = []
    monkeypatch.setattr(server.RDAgentTask, "start", lambda self: started.append(self))
    response = studio_client.post("/upload", data={"scenario": "Finance Data Building", "loops": "1", "all_duration": "1", "confirm_mode": "auto", "confirm_timeout": "0", "objective": "vol"})
    assert response.status_code == 200, response.get_json()
    assert started[-1].confirm == {"mode": "auto", "timeout_min": 0, "instruction": "vol", "gate": True}
    assert studio_client.post("/upload", data={"scenario": "Finance Data Building", "loops": "1", "confirm_mode": "never"}).status_code == 400
    # Resume: the previous run's policy is inherited unless the request names a new one.
    trace_folder = server.app.config["LOG_FOLDER_PATH"]
    (trace_folder / "Finance Data Building" / "demo" / "__session__").mkdir(parents=True, exist_ok=True)
    previous = server._get_or_create_task(str(trace_folder / "Finance Data Building/demo"))
    previous.confirm = {"mode": "all", "timeout_min": 0, "instruction": "old"}
    assert studio_client.post("/resume", json={"id": "Finance Data Building/demo", "loops": 1}).status_code == 200
    assert started[-1].confirm == {"mode": "all", "timeout_min": 0, "instruction": "old"}
    assert studio_client.post("/resume", json={"id": "Finance Data Building/demo", "loops": 1, "confirm_mode": "auto", "confirm_timeout": 0}).status_code == 200
    assert started[-1].confirm == {"mode": "auto", "timeout_min": 0, "instruction": "old", "gate": True}
    assert studio_client.post("/resume", json={"id": "Finance Data Building/demo", "loops": 1, "confirm_mode": "never"}).status_code == 400


@pytest.mark.offline
def test_recent_lists_round_and_run_completions_after_a_cursor(studio_client) -> None:
    trace_folder = server.app.config["LOG_FOLDER_PATH"]
    task = server._get_or_create_task(str(trace_folder / "Finance Data Building/recent"))
    task.messages = [
        {"tag": "feedback.metric", "loop_id": "0", "timestamp": "2026-09-17T02:00:00", "content": {"result": json.dumps({"IC": 0.031}), "workspaces": {"factors": [{"name": "F1"}, {"name": "F2"}]}}},
        {"tag": "feedback.hypothesis_feedback", "loop_id": "0", "timestamp": "2026-09-17T02:01:00", "content": {"decision": True}},
        {"tag": "feedback.hypothesis_feedback", "loop_id": "1", "timestamp": "2026-09-17T02:20:00", "content": {"decision": False}},
        {"tag": "END", "timestamp": "2026-09-17T02:21:00", "content": {"end_code": 0}},
    ]
    everything = studio_client.get("/studio/recent").get_json()
    kinds = [(i["kind"], i.get("round"), i.get("decision"), i.get("ic"), i.get("factors"), i.get("status")) for i in everything["items"] if i["trace"].endswith("recent")]
    assert kinds == [("round_done", 1, True, 0.031, ["F1", "F2"], None), ("round_done", 2, False, None, [], None), ("run_done", None, None, None, None, "completed")]
    later = studio_client.get("/studio/recent", query_string={"since": "2026-09-17T02:10:00"}).get_json()["items"]
    assert [i["kind"] for i in later if i["trace"].endswith("recent")] == ["round_done", "run_done"]
    assert everything["now"]
    assert [i for i in studio_client.get("/studio/recent?region=us").get_json()["items"] if i["trace"].endswith("recent")] == []


@pytest.mark.offline
def test_correlation_names_the_factors_that_do_not_overlap(tmp_path: Path) -> None:
    import pandas as pd
    from rdagent.log.server.studio import factor_correlation

    def write(folder: Path, name: str, dates: list[str], codes: list[str]):
        folder.mkdir(parents=True, exist_ok=True)
        index = pd.MultiIndex.from_product([pd.to_datetime(dates), codes], names=["datetime", "instrument"])
        pd.DataFrame({name: range(len(index))}, index=index, dtype="float64").to_hdf(folder / "result.h5", key="data", mode="w")

    write(tmp_path / "a", "A", ["2025-01-02", "2025-01-03"], ["SH600000", "SZ000001"])
    write(tmp_path / "b", "B", ["2026-09-14", "2026-09-15"], ["AAPL", "MSFT"])
    with pytest.raises(ValueError) as error:
        factor_correlation([("A", tmp_path / "a"), ("B", tmp_path / "b")])
    message = str(error.value)
    assert "A 2025-01-02→2025-01-03（如 SH600000）" in message and "B 2026-09-14→2026-09-15（如 AAPL）" in message
    with pytest.raises(ValueError, match="没有 result.h5"):
        factor_correlation([("A", tmp_path / "a"), ("C", tmp_path / "c")])


@pytest.mark.offline
def test_campaign_power_map_and_stats() -> None:
    from rdagent.log.server import studio_campaign as c

    # Power: 900 days, NASDAQ-like dispersion. 1-day needs ICIR 0.10 (|IC| 0.02); 20-day needs 0.30 (|IC| 0.048): unreachable.
    rows = c.power_table(900, {1: 0.197, 20: 0.161}, members=100)
    by = {r["horizon"]: r for r in rows}
    assert by[1]["icir"] == pytest.approx(0.1) and by[1]["ic"] == pytest.approx(0.0197, abs=1e-4) and by[1]["reachable"] is True
    assert by[20]["icir"] == pytest.approx(0.298, abs=1e-3) and by[20]["reachable"] is False
    assert by[5]["std"] == pytest.approx(3.0 / 10)  # no analysed factor at that horizon: the noise-multiple fallback
    lines = c.power_lines("nasdaq100", 900, 100, rows)
    assert lines[0].startswith("本股票池 nasdaq100（100 只、900 个交易日）过验收线需要：1 日 ICIR ≥ 0.10（|Rank IC| 约 ≥ 0.020）")
    assert "20 日期限要求的 |Rank IC| 超过 0.04" in lines[1] and "可确认的期限：1 日" in lines[1]
    assert c.power_lines("x", None, 100, c.power_table(None, {}, 100)) == []
    # Analysis-only level follows the gate's bars and the magnitude line.
    strong = {"horizons": [{"days": 1, "residual_rank_ic": {"t": -4.0, "mean": -0.03}}]}
    assert c.level_of(strong)[0] == "signal"
    assert c.level_of({"horizons": [{"days": 1, "residual_rank_ic": {"t": 3.5, "mean": 0.01}}]})[0] == "weak"
    assert c.level_of({"horizons": [{"days": 20, "residual_rank_ic": {"t": 1.0, "mean": 0.03}}]})[0] == "noise"
    assert c.level_of(None) == (None, None, None, None)
    # The map: a gate verdict beats an analysis level on the same market; other markets' names are listed apart.
    records = [
        {"name": "PV_DIV_20", "market": "csi300", "level": "weak", "t": -2.7, "horizon": 1, "source": "analysis"},
        {"name": "PV_DIV_20", "market": "csi300", "level": "signal", "t": -4.4, "horizon": 1, "source": "gate"},
        {"name": "PV_DIV_20", "market": "csi1000", "level": "signal", "t": -11.0, "horizon": 1, "source": "analysis"},
        {"name": "PATH_EFF_20", "market": "csi300", "level": "noise", "t": -1.0, "horizon": 1, "source": "gate"},
        {"name": "BETA_60", "market": "nasdaq100", "level": "noise", "t": 0.7, "horizon": 20, "source": "gate"},
        {"name": "BROKEN", "market": "csi300", "level": "error", "t": None, "horizon": None, "source": "analysis"},
    ]
    mapping = c.mechanism_map(records)
    assert mapping["PV_DIV_20"]["csi300"]["t"] == -4.4 and set(mapping["PV_DIV_20"]) == {"csi300", "csi1000"}
    here, elsewhere = c.map_lines(mapping, "csi300")
    assert here.startswith("本市场（csi300）已检验 3 个因子") and "PV_DIV_20：通过 t -4.4（1 日）" in here and "PATH_EFF_20：噪声 t -1.0（1 日）" in here and "BROKEN：未能判断" in here
    assert here.index("PV_DIV_20") < here.index("PATH_EFF_20")  # strongest first
    assert elsewhere.startswith("其他市场检验过、本市场未试的机制") and "BETA_60：nasdaq100 噪声 t 0.7（20 日）" in elsewhere and "PV_DIV_20" not in elsewhere
    us_lines = c.map_lines(mapping, "nasdaq100")
    assert "PV_DIV_20：csi1000 有信号 t -11.0（1 日），csi300 通过 t -4.4（1 日）" in us_lines[1]  # analysis-only vs gate pass
    assert c.map_lines({}, "csi300") == []
    # Campaign statistics over gate verdicts, and the memo prompt built on them.
    gates = [
        {"loop_id": 0, "decision": False, "factors": [{"name": "A", "level": "noise", "reasons": ["t 0.5"]}, {"name": "B", "level": "duplicate", "reasons": ["≈ RVOL"]}]},
        {"loop_id": 1, "decision": True, "factors": [{"name": "C", "level": "signal", "reasons": ["t 5"]}, {"name": "A", "level": "weak", "reasons": ["t 2.2"]}, {"name": "D", "level": "error", "reasons": ["NaN"]}]},
    ]
    stats = c.campaign_stats(gates)
    assert stats["rounds"] == 2 and stats["rounds_passed"] == 1 and stats["factors"] == 5
    assert stats["pass_rate"] == 0.2 and stats["duplicate_rate"] == 0.2 and stats["noise_rate"] == 0.4 and stats["error_rate"] == 0.2
    assert stats["reproposed"] == ["A"] and stats["signals"] == ["C"]
    line = c.stats_lines(stats)[0]
    assert line.startswith("本次研究至今 2 轮、5 个因子：") and "通过率 20%，重复率 20%，噪声率 40%，实现失败率 20%" in line and "重提过的名字：A" in line
    assert c.stats_lines(c.campaign_stats([])) == []
    prompt = c.reflection_prompt(stats, gates, ["记忆行"], "量能结构")
    assert "研究方向：量能结构" in prompt and "第 1 轮：A 噪声（t 0.5）；B 重复（≈ RVOL）" in prompt and "记忆行" in prompt and "不得引用回测收益" in prompt


@pytest.mark.offline
def test_tested_records_join_library_copies_and_gate_verdicts(studio_client, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    trace_folder = server.app.config["LOG_FOLDER_PATH"]
    task = server.rdagent_processes[str(trace_folder / "Finance Data Building/demo")]
    library = [{"name": "STR_5", "market": "csi300", "trace": "Finance Data Building/demo", "loop_id": 0,
                "analysis": {"horizons": [{"days": 1, "residual_rank_ic": {"t": -2.5, "mean": -0.02}}]}, "analysis_error": None},
               {"name": "DEAD", "market": "csi300", "trace": "Finance Data Building/demo", "loop_id": 0, "analysis": None, "analysis_error": "all NaN"}]
    monkeypatch.setattr(studio_module, "REFRESH_ROOT", tmp_path / "traces" / "studio_refresh")
    copy = studio_module.refresh_dir("Finance Data Building/demo", 0, "STR_5", "csi1000")
    copy.mkdir(parents=True)
    (copy / "result.h5").write_bytes(b"")
    (copy / "studio_analysis.csi1000.json").write_text(json.dumps({"status": "completed", "version": studio_module.ANALYSIS_VERSION,
        "source_mtime": (copy / "result.h5").stat().st_mtime, "horizons": [{"days": 1, "residual_rank_ic": {"t": -6.0, "mean": -0.03}}]}))
    task.messages.append({"tag": "studio.gate", "timestamp": "t", "loop_id": 0, "content": {"market": "csi300", "decision": False,
                          "factors": [{"name": "STR_5", "level": "duplicate", "t": -2.5, "horizon": 1, "ic": -0.02}]}})
    with server.app.app_context():
        records = studio_module.tested_records(server.rdagent_processes, trace_folder, library)
    keyed = {(r["name"], r["market"], r["source"]): r for r in records}
    assert keyed[("STR_5", "csi300", "analysis")]["level"] == "weak"
    assert keyed[("STR_5", "csi1000", "analysis")]["level"] == "signal" and keyed[("STR_5", "csi1000", "analysis")]["t"] == -6.0
    assert keyed[("STR_5", "csi300", "gate")]["level"] == "duplicate"
    assert keyed[("DEAD", "csi300", "analysis")]["level"] == "error"
    with server.app.app_context():
        lines = studio_module.campaign_context(server.rdagent_processes, trace_folder, "csi1000", library=library)
    assert any(l.startswith("本股票池 csi1000") for l in lines)
    assert any("本市场（csi1000）已检验 1 个因子" in l and "STR_5：有信号 t -6.0" in l for l in lines)
    assert any("其他市场检验过" in l and "DEAD：csi300 未能判断" in l for l in lines)


@pytest.mark.offline
def test_gate_verdicts_recovered_from_feedback_text() -> None:
    from rdagent.log.server import studio_campaign as c

    text = ("【验收】验收（确定性规则，不经 LLM）：通过。LIMIT_TOUCH_NET_20：通过（与 MAX_RET_20D 相关 +0.57，增量有限；t 值 -15.86，Rank IC -0.0399（1 日）；在 csi300 上复现（t -6.87））；"
            "DRY_DAYS_20_60：偏弱（t 值 3.02（1 日）但 Rank IC 只有 +0.0123，量级不到 0.02，付不起自己的换手）；RET_LAG：噪声（市值中性 Rank IC 的 t 值 -0.86（20 日，线 1.5），与零区分不开）；"
            "X：重复（与库里的 RVOL_20 相关 -0.85，是同一个信号的变体）。\nThe hypothesis is partially supported…")
    parsed = c.parse_gate_summary(text)
    assert parsed["decision"] is True and parsed["recovered"] is True and [f["level"] for f in parsed["factors"]] == ["signal", "weak", "noise", "duplicate"]
    first = parsed["factors"][0]
    assert first == {"name": "LIMIT_TOUCH_NET_20", "level": "signal", "t": -15.86, "horizon": 1, "ic": -0.0399, "nearest": "MAX_RET_20D", "corr": 0.57,
                     "t2": -6.87, "replicated": True, "reasons": ["与 MAX_RET_20D 相关 +0.57，增量有限", "t 值 -15.86，Rank IC -0.0399（1 日）", "在 csi300 上复现（t -6.87）"]}
    assert parsed["factors"][2]["horizon"] == 20 and parsed["factors"][3]["corr"] == -0.85 and parsed["factors"][3]["t"] is None
    assert c.parse_gate_summary("The hypothesis is supported.") is None and c.parse_gate_summary("") is None
    # gate_records: persisted events win; rounds without one are recovered from their feedback; loop order.
    messages = [
        {"tag": "feedback.hypothesis_feedback", "loop_id": "1", "content": {"hypothesis_evaluation": text}},
        {"tag": "feedback.hypothesis_feedback", "loop_id": "0", "content": {"hypothesis_evaluation": "no verdict here"}},
        {"tag": "studio.gate", "loop_id": 2, "content": {"decision": False, "market": "csi1000", "factors": [{"name": "Z", "level": "noise"}]}},
        {"tag": "feedback.hypothesis_feedback", "loop_id": "2", "content": {"hypothesis_evaluation": text}},
    ]
    gates = c.gate_records(messages, "csi1000")
    assert [g["loop_id"] for g in gates] == [1, 2] and gates[0]["market"] == "csi1000" and gates[0]["recovered"] is True
    assert gates[1]["factors"] == [{"name": "Z", "level": "noise"}] and "recovered" not in gates[1]


@pytest.mark.offline
def test_review_gaps_memory_route_submit_branch_replay_and_reflection_failure(studio_client, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from rdagent.log.server import studio_llm

    trace_folder = server.app.config["LOG_FOLDER_PATH"]
    # GET /studio/memory: the lines a run on the market would start with; the market is validated.
    data = studio_client.get("/studio/memory?market=csi300").get_json()
    assert data["market"] == "csi300" and any(line.startswith("本股票池 csi300") for line in data["lines"])
    assert studio_client.get("/studio/memory?market=../x").status_code == 400
    # A hand-written direction submitted through /user_interaction/submit gets the memory attached too.
    task = server.rdagent_processes[str(trace_folder / "Finance Data Building/demo")]
    replies = []
    task.user_response_q = type("Q", (), {"put": lambda self, payload, **k: replies.append(payload)})()
    task.messages.append({"tag": "user_interaction.request", "timestamp": "2026-09-19T00:00:00+00:00", "content": {"user_instruction": None}})
    assert studio_client.post("/user_interaction/submit", json={"id": "Finance Data Building/demo", "payload": {"user_instruction": "看成交额结构"}}).status_code == 200
    assert replies[-1]["user_instruction"].startswith("看成交额结构\n\n研究记忆（Studio 自动附上）：") and task.confirm["instruction"] == "看成交额结构"
    # Persisted events come back when the trace is reloaded from RD-Agent's log.
    folder = trace_folder / "Finance Data Building/demo"
    server.record_event(task, {"tag": "studio.gate", "timestamp": "t", "loop_id": 0, "content": {"decision": True, "factors": [], "market": "csi300"}})
    monkeypatch.setattr(server, "FileStorage", lambda path: type("FS", (), {"iter_msg": lambda self: iter([])})())
    monkeypatch.setattr(server, "WebStorage", lambda **k: None)
    server.read_trace(folder, id=str(folder))
    reloaded = server.rdagent_processes[str(folder)].messages
    assert [m["tag"] for m in reloaded if m["tag"] == "studio.gate"] == ["studio.gate"] and reloaded[0]["content"]["decision"] is True
    # A reflection whose model call fails is recorded on the verdict and does not raise.
    monkeypatch.setattr(studio_llm, "complete", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("quota")))
    with pytest.raises(RuntimeError):
        server.reflect(task, "csi300", [{"loop_id": 0, "decision": False, "factors": []}], [], 0)
    # OpenCode mirror without /v1: the Anthropic-format endpoint is still named in full, and the model list
    # is fetched from the gateway root rather than the model's endpoint.
    r = studio_llm.resolve({"provider": "opencode", "model": "qwen3.8-max", "base_url": "https://mirror.example"})
    assert r["base_url"] == "https://mirror.example/v1/messages" and r["gateway_base"] == "https://mirror.example"
    r = studio_llm.resolve({"provider": "opencode", "model": "qwen3.8-max", "base_url": "https://mirror.example/v1/"})
    assert r["base_url"] == "https://mirror.example/v1/messages"
    # Only failures that come from the signal itself are permanent; a transient one is retried.
    assert studio_module.permanent_failure("factor has no valid values: all 10 rows are NaN") and not studio_module.permanent_failure("HDF5 file locked")
    ws = tmp_path / "ws" / "f0"
    (ws / "studio_analysis.csi300.json").write_text(json.dumps({"status": "failed", "source_mtime": (ws / "result.h5").stat().st_mtime, "error": "HDF5 file locked"}))
    assert studio_module.failed_analysis(ws, "csi300") is None
    (ws / "studio_analysis.csi300.json").write_text(json.dumps({"status": "failed", "source_mtime": (ws / "result.h5").stat().st_mtime, "error": "factor has no observations inside csi300"}))
    assert studio_module.failed_analysis(ws, "csi300").startswith("factor has no observations")


@pytest.mark.offline
def test_extra_fields_load_attach_and_job(studio_client, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from rdagent.log.server import studio_extra

    cache = tmp_path / "traces" / "studio_data" / "extra" / "baostock"
    cache.mkdir(parents=True)
    (cache / "SH600000.csv").write_text("date,code,close,volume,amount,turn,peTTM,pbMRQ,psTTM,pcfNcfTTM,isST\n"
                                        "2025-01-02,sh.600000,10.0,1000000,10000000,0.5,8.5,0.9,1.2,-3.0,0\n"
                                        "2025-01-03,sh.600000,10.5,2000000,21000000,0,8.9,0.95,1.3,-3.1,1\n")
    (cache / "SZ000001.csv").write_text("date,code,close,volume,amount,turn,peTTM,pbMRQ,psTTM,pcfNcfTTM,isST\n")  # fetched, nothing there
    assert studio_extra.bs_code("SH600000") == "sh.600000" and studio_extra.qlib_code("sz.000001") == "SZ000001"
    extra = studio_extra.load(cache, ["SH600000", "SZ000001", "SH600004"])
    assert list(extra.columns) == studio_extra.EXTRA_COLUMNS and len(extra) == 2
    first = extra.loc[(pd.Timestamp("2025-01-02"), "SH600000")]
    assert first["$turnover"] == pytest.approx(0.005) and first["$float_cap"] == pytest.approx(10.0 * 1_000_000 / 0.005) and first["$is_st"] == 0
    second = extra.loc[(pd.Timestamp("2025-01-03"), "SH600000")]
    assert pd.isna(second["$float_cap"]) and second["$is_st"] == 1  # zero turnover: no float cap
    # attach: left join onto an OHLCV frame; rows without a source row stay NaN; a foreign universe stays untouched.
    days = pd.to_datetime(["2025-01-02", "2025-01-03", "2025-01-06"])
    index = pd.MultiIndex.from_product([days, ["SH600000", "SH600004"]], names=["datetime", "instrument"])
    ohlcv = pd.DataFrame({"$close": 1.0, "$volume": 2.0}, index=index)
    joined, attached = studio_extra.attach(ohlcv, cache)
    assert attached and list(joined.columns) == ["$close", "$volume", *studio_extra.EXTRA_COLUMNS]
    assert joined.loc[(days[0], "SH600000"), "$pe_ttm"] == pytest.approx(8.5) and pd.isna(joined.loc[(days[2], "SH600000"), "$pe_ttm"])
    assert pd.isna(joined.loc[(days[0], "SH600004"), "$turnover"])
    us = pd.DataFrame({"$close": 1.0}, index=pd.MultiIndex.from_product([days, ["AAPL"]], names=["datetime", "instrument"]))
    assert studio_extra.attach(us, cache)[1] is False and studio_extra.attach(us, tmp_path / "nowhere")[1] is False
    # Status and the job: member codes from the instrument lists, the fetch subprocess, exports rebuilt.
    monkeypatch.setattr(studio_module, "EXTRA_CACHE", cache)
    status = studio_client.get("/studio/data/extra").get_json()
    assert status["instruments"] == 2 and status["last"] == "2025-01-03" and status["columns"] == studio_extra.EXTRA_COLUMNS
    calls = []
    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        return type("P", (), {"stdout": json.dumps({"status": "completed", "done": 2, "updated": 2, "empty": 0, "failed": [], "failed_count": 0}), "stderr": "", "returncode": 0})()
    monkeypatch.setattr(studio_module.subprocess, "run", fake_run)
    monkeypatch.setattr(studio_module, "workers_busy", lambda app: False)
    started = studio_client.post("/studio/data/extra", json={"markets": ["csi1000"]})
    assert started.status_code == 202, started.get_json()
    job = wait_job(studio_client, started.get_json()["job"])
    assert job["status"] == "completed", job
    assert job["result"]["updated"] == 2 and "rebuilt" in job["result"]
    fetch_cmd = calls[0]
    assert fetch_cmd[2] == "fetch" and fetch_cmd[3] == str(cache) and Path(fetch_cmd[4]).read_text().splitlines()  # member codes were written
    assert studio_client.post("/studio/data/extra", json={"markets": ["nasdaq100"]}).status_code == 400


@pytest.mark.offline
def test_analysis_cache_survives_a_rewrite_with_the_same_content(tmp_path: Path) -> None:
    days = pd.bdate_range("2025-01-01", periods=4)
    index = pd.MultiIndex.from_product([days, ["A", "B"]], names=["datetime", "instrument"])
    frame = pd.Series(range(len(index)), index=index, dtype=float).to_frame("x")
    ws = tmp_path / "ws"; ws.mkdir()
    frame.to_hdf(ws / "result.h5", key="data")
    stamp = studio_module.source_stamp(ws / "result.h5")
    (ws / "studio_analysis.csi300.json").write_text(json.dumps({"status": "completed", "version": studio_module.ANALYSIS_VERSION, **stamp, "rank_ic": {"mean": 0.02}}))
    assert studio_module.cached_analysis(ws, "csi300")["rank_ic"]["mean"] == 0.02
    # RD-Agent re-runs the code next round: same bytes, new mtime → still valid.
    import os, time
    os.utime(ws / "result.h5", (time.time() + 100, time.time() + 100))
    assert studio_module.cached_analysis(ws, "csi300") is not None
    # Different content → invalid; a record from before hashing falls back to the mtime rule.
    (frame * 2).to_hdf(ws / "result.h5", key="data")
    assert studio_module.cached_analysis(ws, "csi300") is None
    (ws / "studio_analysis.csi300.json").write_text(json.dumps({"status": "completed", "version": studio_module.ANALYSIS_VERSION, "source_mtime": (ws / "result.h5").stat().st_mtime, "rank_ic": {"mean": 0.03}}))
    assert studio_module.cached_analysis(ws, "csi300")["rank_ic"]["mean"] == 0.03


@pytest.mark.offline
def test_neutralize_removes_size_and_industry_from_the_score() -> None:
    import numpy as np
    from rdagent.log.server.studio_worker import neutralize, validate_config

    days = pd.bdate_range("2025-01-01", periods=3)
    names = [f"S{i}" for i in range(40)]
    index = pd.MultiIndex.from_product([days, names], names=["datetime", "instrument"])
    rng = np.random.RandomState(0)
    size = pd.Series(np.tile(np.linspace(10, 14, 40), 3), index=index)  # log traded value, same each day
    industry = {n: ("A" if i % 2 else "B") for i, n in enumerate(names)}
    # A score that is pure size plus an industry offset plus noise: after neutralisation only the noise is left.
    noise = pd.Series(rng.randn(len(index)), index=index)
    score = size * 3 + pd.Series([5.0 if industry[n] == "A" else 0.0 for _, n in index], index=index) + noise
    out = neutralize(score, size, industry)
    assert set(out.index) == set(score.index)
    for day in days:
        d = out.loc[day]
        raw = abs(np.corrcoef(score.loc[day].rank().to_numpy(), size.loc[day].to_numpy())[0, 1])
        left = abs(np.corrcoef(d.to_numpy(), size.loc[day].to_numpy())[0, 1])
        assert raw > 0.7 and left < 0.2  # the score was mostly size; the residual is not
        by = d.groupby(pd.Series(industry)).mean()
        assert abs(by["A"] - by["B"]) < 0.05  # industry means gone
    # Without an industry map only size is removed; a stock without size is dropped.
    out2 = neutralize(score, size.drop((days[0], "S0")), None)
    assert (days[0], "S0") not in out2.index and len(out2) == len(score) - 1
    base = {"start": "2025-01-01", "end": "2025-02-01", "market": "csi300", "factors": [{"name": "F", "path": "/tmp/x", "weight": 1}]}
    assert validate_config(base)["neutral"] == "none" and validate_config({**base, "neutral": "size_industry"})["neutral"] == "size_industry"
    with pytest.raises(ValueError):
        validate_config({**base, "neutral": "beta"})


@pytest.mark.offline
def test_hold_scores_offsets_and_staggered_average() -> None:
    from rdagent.log.server.studio_worker import hold_scores, staggered_scores

    days = pd.bdate_range("2025-01-01", periods=8)
    index = pd.MultiIndex.from_product([days, ["A", "B"]], names=["datetime", "instrument"])
    score = pd.Series(range(16), index=index, dtype=float)  # day d: A = 2d, B = 2d + 1
    held = hold_scores(score, 4)
    assert held.loc[(days[3], "A")] == 0 and held.loc[(days[4], "A")] == 8  # blocks start at day 0 and day 4
    shifted = hold_scores(score, 4, 2)
    assert shifted.loc[(days[1], "A")] == 0 and shifted.loc[(days[2], "A")] == 4 and shifted.loc[(days[5], "A")] == 4 and shifted.loc[(days[6], "A")] == 12
    both = staggered_scores(score, 4, 2)
    assert both.loc[(days[3], "A")] == pytest.approx((0 + 4) / 2) and both.loc[(days[6], "A")] == pytest.approx((8 + 12) / 2)
    assert staggered_scores(score, 1, 5).equals(score)
