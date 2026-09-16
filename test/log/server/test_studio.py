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
    monkeypatch.setattr(studio_module.subprocess, "Popen", lambda *a, **k: type("P", (), {"poll": lambda self: None})())
    server.rdagent_processes.clear()
    _task_with_metric(trace_folder, "Finance Data Building/demo", workspace_root)
    return server.app.test_client()


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
        "id": "Finance Data Building/second", "scenario": "Finance Data Building", "rounds": 2, "accepted": 1,
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

    def fake_refresh(code_path: Path, name: str, out_dir: Path):
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
    assert response.status_code == 200, response.get_json()
    assert response.get_json()["end"] == "2026-09-11"

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
    # Guards: unknown scenario, missing session, bad loop count.
    assert studio_client.post("/resume", json={"id": "General Model Implementation/x", "loops": 1}).status_code == 400
    assert studio_client.post("/resume", json={"id": "Finance Data Building/nosession", "loops": 1}).status_code == 404
    assert studio_client.post("/resume", json={"id": "Finance Data Building/demo", "loops": 0}).status_code == 400


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
    payload = updated.get_json()
    assert payload["start"] == "2025-01-02" and payload["end"] == "2025-12-31" and payload["failures"] and not payload["refreshed"]
    detail = studio_client.get(f"/studio/strategies/{strategy['id']}").get_json()
    assert [r["kind"] for r in detail["run_details"]] == ["evidence", "update"]
    assert detail["run_details"][1]["status"] == "queued" and detail["run_details"][1]["end"] == "2025-12-31"
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


@pytest.mark.offline
def test_research_from_strategy_seeds_base_features(studio_client, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (tmp_path / "ws" / "f0" / "factor.py").write_text("print('STR_5')")
    monkeypatch.setattr(server, "upload_folder_path", tmp_path / "uploads")
    monkeypatch.setattr(server, "universe_env", lambda market: {"QLIB_FACTOR_MARKET": market})
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
    assert task.env == {"QLIB_FACTOR_MARKET": "csi300"}
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
        out = Path(cmd[-1]); (out / "full").mkdir(parents=True); (out / "full" / "daily_pv.h5").write_bytes(b"")
        return type("P", (), {"stdout": '{"status": "completed"}', "stderr": ""})()

    monkeypatch.setattr(server.subprocess, "run", fake_run)
    env = server.universe_env("csi1000")
    assert env["QLIB_FACTOR_MARKET"] == "csi1000" and env["QLIB_FACTOR_BENCHMARK"] == "SH000852"
    assert env["FACTOR_COSTEER_DATA_FOLDER"].endswith("universe/csi1000/full") and calls and calls[0][3] == "csi1000"
    server.universe_env("csi1000")  # already built: no second subprocess
    assert len(calls) == 1
    with pytest.raises(ValueError):
        server.universe_env("nasdaq")


@pytest.mark.offline
def test_upload_passes_the_universe_to_the_run(studio_client, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(server, "upload_folder_path", tmp_path / "uploads")
    monkeypatch.setattr(server, "universe_env", lambda market: {"QLIB_FACTOR_MARKET": market, "FACTOR_COSTEER_DATA_FOLDER": "/data/" + market})
    started = []
    monkeypatch.setattr(server.RDAgentTask, "start", lambda self: started.append(self))
    response = studio_client.post("/upload", data={"scenario": "Finance Data Building", "loops": "2", "all_duration": "1", "market": "csi1000"})
    assert response.status_code == 200, response.get_json()
    assert started[0].env == {"QLIB_FACTOR_MARKET": "csi1000", "FACTOR_COSTEER_DATA_FOLDER": "/data/csi1000"}
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
        "trace": "Finance Data Building/demo", "loop_id": 0, "name": "STR_5",
        "description": "Short-term reversal", "formulation": "-r_5", "variables": {"$close": "close"},
        "hypothesis": "h", "decision": True, "reason": "improves return",
        "metrics": {"IC": 0.01, "Rank IC": 0.02}, "code": "print(5)", "analysis": None, "refreshed": None, "coverage": None,
    }]


@pytest.mark.offline
def test_validate_config_checks_benchmark() -> None:
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
    analysis_cache_path(ws, "csi300").write_text(json.dumps({"status": "completed", "source_mtime": (ws / "result.h5").stat().st_mtime, "days": 3}))
    assert cached_analysis(ws, "csi300")["days"] == 3
    analysis_cache_path(ws, "csi300").write_text(json.dumps({"status": "completed", "source_mtime": 0, "days": 3}))
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
