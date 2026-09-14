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
