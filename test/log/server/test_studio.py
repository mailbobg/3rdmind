import json
from pathlib import Path

import pandas as pd
import pytest

from rdagent.core.experiment import Experiment, FBWorkspace, Task
from rdagent.log.ui.storage import WebStorage


class _FactorTask(Task):
    def __init__(self, name: str) -> None:
        super().__init__(name=name, description="")
        self.factor_name = name

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


from rdagent.log.server.studio_worker import validate_config, load_factor_frame


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


import rdagent.log.server.app as server
from rdagent.log.server import studio as studio_module


def _task_with_metric(trace_folder: Path, trace_id: str, factor_dir: Path):
    task = server._get_or_create_task(str(trace_folder / trace_id))
    task.messages = [
        {"tag": "research.hypothesis", "loop_id": 0, "timestamp": "t", "content": {"hypothesis": "h"}},
        {
            "tag": "feedback.metric", "loop_id": 0, "timestamp": "t",
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
    monkeypatch.setattr(studio_module, "WORKSPACE_ROOT", workspace_root)
    monkeypatch.setattr(studio_module.subprocess, "Popen", lambda *a, **k: type("P", (), {"poll": lambda self: None})())
    server.rdagent_processes.clear()
    _task_with_metric(trace_folder, "Finance Data Building/demo", workspace_root)
    return server.app.test_client()


@pytest.mark.offline
def test_rounds_lists_factor_rounds(studio_client) -> None:
    response = studio_client.get("/studio/rounds", query_string={"trace": "Finance Data Building/demo"})
    assert response.status_code == 200
    assert response.get_json() == [{"loop_id": 0, "factors": ["STR_5"], "metrics": {"IC": 0.01, "Rank IC": 0.02}}]
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
    assert config["factors"] == [{"name": "STR_5", "weight": 1.0, "path": str(tmp_path / "ws" / "f0")}]
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
